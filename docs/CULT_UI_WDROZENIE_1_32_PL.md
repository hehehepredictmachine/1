# CULT UI – raport wdrożenia (1.32.0)

Zakres zgodnie z „PEPEMARKETWIZARD – UI IMPLEMENTATION MASTER PROMPT” (scope lock): **tylko** siedem zaprojektowanych elementów.
Grafiki pochodzą z paczki `projekt.zip` (menu.jpg, launcher.jpg, instrukcja.jpg, lig.jpg, wind.jpg, ai.jpg, controltower.jpg,
strategy.png i cztery tekstury). Nie dodano wież, zakładek, produktów, subskrypcji ani modułów. Backend, MT5, Telegram, strategie,
progi domyślne, ryzyko, koszty i tryby wykonania działają jak dotąd. Wcześniejsza praca „menu czterech wież i baniek” została
przerwana na Twoje polecenie i nie weszła do wydania.

## 1. Co zbudowano

| # | Element | Gdzie | Stan |
|---|---------|-------|------|
| 1 | Main Menu – miasto, 6 wież (Lightning, Ice, Wind, Control, Strategy Lab, Fire) | `#/menu`, `features/cult/CultMenu.tsx` | działa, testy UI |
| 2 | Launcher „JOIN THE CULT” jako osobne małe okno | Windows: `desktop/splash.html` + `app_windows.go`; przeglądarka: `Launcher.tsx` | przeglądarka: testy UI; Windows: zob. §8 |
| 3 | Main Menu Motion System (HYBRID CINEMATIC 5D, intro 6 s) | `cult.css` (storyboard `ci-*`), `CultMenu.tsx` | działa, zrzuty klatek 0,4 / 1,3 / 2,2 / 4,1 / 5,2 s |
| 4 | Lightning Tower – Live Signals Center | `#/lightning`, `LightningTower.tsx` | działa na danych bota |
| 5 | Wind Portal – AI Engine Core | `#/wind`, `WindPortal.tsx` | działa na danych bota |
| 6 | Control Tower – Bot Management Center | `#/control`, `ControlTower.tsx` | działa, zapis do konfiguracji bota |
| 7 | Strategy Lab | `#/strategy-lab`, `StrategyLab.tsx` | działa; części bez backendu oznaczone |

**Przepływ startu:** aplikacja Windows → małe okno launchera (postęp, wybór danych, błąd + „Spróbuj ponownie”, logi, zamknij) →
**SYSTEM READY** (silnik bota już działa w tle) → **JOIN THE CULT** → okno rośnie do 85 % obszaru roboczego monitora, wyśrodkowane →
panel `?pmw_joined=1#/menu?intro=1` → intro 6 s (raz; „Pomiń intro” / Esc) → Main Menu. Restart silnika z panelu przeładowuje panel
bez launchera i bez intro. W przeglądarce launcher pojawia się na początku sesji pod gołym adresem; panel nie jest montowany przed
kliknięciem, przycisk czeka na stan bota i WebSocket. Bezpośredni link do ekranu (`#/...`) i `?pmw_joined=1` pomijają launcher.

**Motion system:** intro – ciemność i logo (0,0–0,8 s), miasto (0,8–1,6), rdzeń energii (1,6–2,4), wieże (2,4–3,6), czarodzieje
Pepe i efekty żywiołów (3,6–4,8), slogan i menu (4,8–6,0). Najechanie na wieżę: podświetlenie, impuls energii, podgląd z bieżącą
wartością z bota; kliknięcie / Enter: przybliżenie kamery do wieży → panel. Ruch postaci w spoczynku, wartości odświeżane w miejscu.
Ograniczone animacje systemu (`prefers-reduced-motion`): bez intro, bez ruchu, bez przybliżenia – nawigacja natychmiastowa.

## 2. Zmienione i nowe pliki

* **Backend:** `backend/masterquo/sysres.py` (nowy – CPU/RAM komputera bota, Windows i Linux), `backend/masterquo/presets.py` (nowy –
  presety sterowania strategią w `data/presets/strategy.json`), `backend/masterquo/config.py` (lista zmiennych szablonu i ich walidacja –
  bez nowych pól modelu), `backend/masterquo/notify/telegram.py` (szablon w osobnym pliku `data/telegram/signal_template.json`,
  podgląd, test z szablonem), `backend/masterquo/runtime.py` (ścieżka pliku szablonu), `backend/masterquo/api/app.py` (nowe
  endpointy, §4), `backend/masterquo/version.py` (1.32.0).
* **Frontend:** nowy katalog `frontend/src/features/cult/` (`CultMenu`, `Launcher`, `CultShell`, `LightningTower`, `WindPortal`,
  `ControlTower`, `StrategyLab`, `kit`, `data`, `assets`, `cult.css`), grafiki `frontend/public/assets/cult/` (41 plików,
  `zrodla.json` z wycinkami i sumami), `App.tsx` (bramka launchera, gałąź CULT), `router.ts` (strony lightning / wind / control /
  strategy-lab, mapa ekranów), `components/Dialogs.tsx` (`ModeDialog` z trybem początkowym dla autopilota). Usunięte: menu trzech
  wież 3D z 1.26 (`WizardMenu`, `TowerMenu`, `TowerScene`, `BackdropFx`, `webgl`, tło menu) i zależność `three`. Mapy przepływu modułów
  (`FlowGraph`) zostały zachowane – są w Wind Portal → NEURAL DATA FLOW.
* **Desktop:** `desktop/splash.html` (launcher), `desktop/app_windows.go` (małe okno, akcja `join`, stan READY, powiększenie i
  wyśrodkowanie na monitorze okna), `desktop/window.go` (nowy – rozmiary, środek, adres panelu), `desktop/assets/` (grafika launchera
  wbudowana w EXE), `desktop/winres/winres.json` (1.32.0), `desktop/desktop_test.go`.
* **Narzędzia:** `tools/cult_assets.py` (nowy – wycinanie warstw z grafik, usuwanie wpalonych napisów i liczb), `tools/build_release.py`,
  `tools/make_manuals.py`, `tools/verify_release.py` (wersja i opis).
* **Testy:** `tests/test_ui_cult.py` (nowy), `tests/test_cult_backend.py` (nowy), zaktualizowane `tests/test_ui_pages.py`,
  `tests/test_ui_wizard.py`, `tests/test_ui_interface_129.py`; `tests/test_risk_execution.py` – oczekiwana lista migracji bazy
  uzupełniona o 0024 (Kronos, dodana w 1.31 bez aktualizacji tego testu; czerwony już na 1.31.0, bez związku z CULT UI).
* **Dokumenty:** `CHANGELOG.md`, `START_TUTAJ_PL.md`, ten raport, instrukcje PDF (`release/Instrukcja_*.pdf`, `tools/make_manuals.py`), `release/RAPORT_KONCOWY.md`.

## 3. Mapa źródeł danych

Każda wartość ma znacznik rodzaju danych: **REAL** (rachunek potwierdzony przez terminal jako rzeczywisty), **DEMO** (rachunek demo
MT5), **DEMO · symulator** (symulator terminala – dane syntetyczne), **brak danych**, **nieaktualne** (ostatnia odpowiedź starsza niż
2,5 × okres odświeżania albo brak łącza z botem), **błąd synchronizacji** (zapytanie nie powiodło się). Dane rynkowe i wyniki z
symulatora nigdy nie są oznaczane jako REAL (sprawdza to test). REAL na symulatorze mają tylko pomiary samego bota: stan modułów
z katalogu (Lightning → AI ENGINE STATUS) i CPU / RAM (Control Tower → Infrastructure).

| Panel / element | Źródło |
|---|---|
| Menu: TOTAL P/L, WIN RATE | `/api/v1/stats` (`account_roi` – ROI 30 dni metodą Dietza, `bot.all` – zamknięte transakcje bota) |
| Menu: ACTIVE SIGNALS | `/api/v1/bot-signals` (status OPEN / ACTIVE / PENDING) |
| Menu: AUM (TRADING) | equity rachunku MT5 ze strumienia WebSocket |
| Menu: podgląd wieży | stan ze strumienia (tryb, STOP, symbol, jakość danych, pozycje), `/api/v1/models/catalog` |
| Lewy panel: SYSTEM / LATENCY | stan WebSocket, czas odpowiedzi `/api/v1/health` (co 10 s) |
| Powiadomienia | ostrzeżenia silnika + wpisy WARNING / ERROR dziennika |
| Lightning: wykres | świece MT5 aktywnego symbolu (ChartPanel), poziomy planu sygnału |
| Lightning: AI ENGINE STATUS, CONSENSUS | `/api/v1/models/catalog`, `/api/v1/models/predictions` (tylko gotowe predykcje), Monte Carlo P(+L) |
| Lightning: LIVE SIGNALS, LIFECYCLE, SELECTED SIGNAL | `/api/v1/bot-signals` (plan, etapy, walidacja), `/api/v1/setups` |
| Lightning: MARKET ALERTS | `/api/v1/news`, spread vs limit z konfiguracji, unieważnione setupy, ostrzeżenia, dziennik |
| Wind: karty XGBOOST / ML / MONTE CARLO | `/api/v1/models/catalog` (rodziny modeli), `/api/v1/montecarlo/status` |
| Wind: AI CONSENSUS CORE / MATRIX | `/api/v1/models/evidence` (jeden głos na grupę skorelowaną, wagi z walidacji walk-forward) |
| Wind: DECISION TRACE | `/api/v1/decision` (drzewo decyzji silnika S01–S12) |
| Wind: SCENARIO SIMULATION | `/api/v1/montecarlo/scenarios` (nieskalibrowane – tak oznaczone) |
| Wind: ANOMALY / MTF / COGNITION | `/api/v1/ml/status` (dryf), `/api/v1/context-tf`, `/api/v1/liquidity/context`, `/api/v1/news` |
| Wind: NEURAL DATA FLOW + mapy modułów | strumień (tick, cykl silnika), `/api/v1/analytics/diagnostics`, `/api/v1/telemetry` |
| Control: PERFORMANCE | `/api/v1/stats` (24H / 7D / 30D / ALL, per symbol, per silnik, dzienny P/L) |
| Control: STRATEGY CONTROL | `/api/v1/config`, `/api/v1/setups`, `/api/v1/sh` (modele SH) |
| Control: RISK, TELEGRAM, DATA QUALITY | `/api/v1/config`, `/api/v1/telegram`, `/api/v1/telegram/preview`, jakość z decyzji silnika |
| Control: AUTOPILOT | tryb ze strumienia; zmiana tylko w oknie trybów (potwierdzenie rachunku dla AUTO) |
| Control: INFRASTRUCTURE, AUDIT | `/api/v1/system/resources`, ping MT5, stan Telegram, `/api/v1/logs` |
| Strategy Lab | `/api/v1/setups` (rejestr S01–S12, SCALPING / HEDGING), `/api/v1/strategy/auto`, `/api/v1/config`, `/api/v1/decision`, `/api/v1/stats`, `/api/v1/bot-signals` |

## 4. Zapis ustawień (Control Tower, Strategy Lab)

Wszystko trafia do rzeczywistej konfiguracji bota przez istniejący, walidowany zapis (`PUT /api/v1/config` – ten sam co w
Ustawieniach, ze strażnikiem trybu wykonania) i obowiązuje od następnej decyzji. Po zapisie panel wczytuje stan z backendu;
nieprawidłową wartość backend odrzuca, a panel pokazuje błąd (test: ryzyko 99 % na transakcję → odmowa, konfiguracja bez zmian).

| Ustawienie | Zapis |
|---|---|
| Active Strategy (AUTO / S01–S12) | `POST /api/v1/strategy/mode` |
| Consensus Threshold / Min. Confidence | `active.thresholds.confirmed` / `.early` (ocena setupu 0–100 – heurystyka, nie prawdopodobieństwo) |
| Trade Filters | `risk.macro_block_high_impact`, `strategy.d1_conflict_blocks_entry`, `risk.max_spread_points` |
| Risk per Trade, Daily Loss Limit, Max Drawdown, Max Open Positions | `risk.*` |
| Auto Trading Stop | `POST /api/v1/kill` (STOP nowych wejść, z potwierdzeniem; wznowienie bez) |
| Emergency Kill Switch | istniejące okno zamykania pozycji (wpisanie „ZAMKNIJ”) |
| Telegram: szablon | `PUT /api/v1/telegram/template` → `data/telegram/signal_template.json` (walidacja przed zapisem) |
| Telegram: Trade Signal, Trade Open/Close, Daily Summary | `telegram.send_signals`, `send_trades`, `send_stats` |
| Presety (Save / Load / Reset) | `POST /api/v1/presets/strategy[/load|/reset]` – tylko pola sterowania strategią (§2), dziennik PRESET_LOADED / PRESET_RESET |
| TEST STRATEGY / DEPLOY TO BOT | `POST /api/v1/strategy/toggle` (scan ON + trade OFF / trade ON), z potwierdzeniem; o zleceniach decyduje dalej tryb wykonania |

Szablon Telegram przyjmuje tylko zmienne `{symbol} {direction} {entry} {sl} {tp} {tp1} {strategy} {timeframe} {stage}`; podgląd
używa ostatniego sygnału albo przykładu oznaczonego „[EXAMPLE – not a signal]”; bot zawsze dopisuje znacznik symulatora i „Analysis
only – not an order.”. Uszkodzony szablon nie psuje wysyłki – bot wraca do formatu wbudowanego.

## 5. Elementy wizualizacji bez odpowiednika w bocie (pokazane uczciwie, nie udawane)

* **Random Forest** – bot nie ma takiego modelu: karta „BRAK W BOCIE” z wyjaśnieniem.
* **Model Weights** – tylko do odczytu (wagi z walidacji walk-forward), nie ustawia się ich ręcznie.
* **Backup data feed** – bot ma jedno źródło (MT5): „brak”.
* **Performance Report** (Telegram) – brak takiej wiadomości: przełącznik nieaktywny.
* **Okresy 90D / YTD**, **Sharpe**, **Stability** – API ich nie liczy: wyłączone / „bot nie liczy”.
* **Strategy Lab: Advanced Editor, Condition Wizard, AI Assistant, Strategy Evolution** – bot nie ma edytora własnych strategii ani
  aktywnego optymalizatora: oznaczone „wymaga doprecyzowania”, przycisk Evolution nieaktywny.
* **Filtry Smart Money / Smart Odds / Volatility / Liquidity** – nie są osobnymi ustawieniami bota: pokazane tylko jako kontekst.
* **Community / Membership / Accounts / Backtest Lab** – nie istnieją w bocie, więc nie ma ich w menu.
* **Domena pepemarketwizard.io** z launchera – pominięta (bot działa lokalnie).
* **Semi-Auto „Confirm Trades”** – bot nie ma potwierdzania pojedynczych transakcji; kafel SEMI-AUTO otwiera tryb PAPER (symulacja).

## 6. Do doprecyzowania (pytania)

1. Czy Ice Tower ma prowadzić do widoku Precision (obecnie), a Fire Tower do Trading Intelligence (obecnie)?
2. SEMI-AUTO: czy zostawić odwzorowanie na PAPER, czy zbudować potwierdzanie pojedynczych transakcji (nowa funkcja – poza zakresem)?
3. Strategy Lab: czy Advanced Editor / Condition Wizard / AI Assistant / Strategy Evolution mają powstać (wymaga zaprojektowania
   edytora strategii i backendu), czy pozostają oznaczone jako niedostępne?
4. Random Forest i zapasowe źródło danych: usunąć z wizualizacji czy zostawić z oznaczeniem „brak w bocie”?
5. Raport „Performance Report” w Telegram, okresy 90D / YTD, Sharpe / Stability – czy dodać ich obliczanie w bocie?
6. Launcher Windows: czy zostawić dotychczasowe zachowanie (silnik startuje od razu, panel po JOIN), czy JOIN ma też uruchamiać silnik?

## 7. Bezpieczeństwo i ograniczenia

* Nawigacja (wieże, menu, zakładki) nie wysyła zleceń i nie zmienia trybu – sprawdzają to testy (brak zapytań order / trade /
  execution / close / positions / mode). Execution Lock pozostaje wycofany; wybór trybu SIGNALS / PAPER / AUTO DEMO / AUTO LIVE,
  STOP nowych wejść, limity użytkownika i wymagania brokera działają bez zmian.
* Mostek okna Windows (`window.pmw`) działa tylko na ekranie launchera; akcja `join` jest przyjmowana tylko w stanie READY.
* Launcher nie ładuje niczego z sieci (grafika wbudowana w EXE).
* Grafiki z projektu są wycinane deterministycznie (`tools/cult_assets.py`, plik `zrodla.json` z prostokątami i sumami SHA-256);
  wpalone w grafiki liczby (np. „88,4 %”, ROI, win ratio) są usuwane i zastępowane wartościami z bota.

## 8. Testy

Wyniki uruchomień – w `release/RAPORT_KONCOWY.md` (sekcja 1.32.0). Okno Windows (WebView2) nie mogło zostać uruchomione w tym
środowisku (Linux): sprawdzono kompilację krzyżową i `go vet` dla Windows, testy Go logiki rozmiarów / adresu / strony launchera
oraz wygląd i akcje `splash.html` w Chromium z atrapą mostka (stany: postęp, wybór danych, błąd, READY, kliknięcie JOIN →
akcja `join`). Zachowanie na prawdziwym Windows (powiększenie okna, monitor z paskiem zadań, skalowanie DPI) – **nie sprawdzono**.

## 9. Powrót do 1.31.0

Paczka `PepeMarketWizard_DESKTOP_1_31_0.zip` (commit `da076c8`). Dane są wspólne. 1.32 nie dodaje żadnego klucza do `config.json`
(modele konfiguracji są ścisłe – nowy klucz zatrzymałby 1.31): szablon Telegram i presety leżą w osobnych plikach
`data/telegram/signal_template.json` i `data/presets/strategy.json`, których 1.31 nie czyta. Sprawdzono: konfiguracja zapisana przez
1.32 jest wczytywana przez kod 1.31 bez błędu. Po powrocie wiadomości sygnałów wracają do formatu wbudowanego.
