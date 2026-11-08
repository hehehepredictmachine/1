# CHANGELOG

## 1.36.0 (w repozytorium, bez nowej paczki) – Main Menu V2 (8 wież) + wieże PEPE$WTC V4 i PEPE$SIGNAL V1
* **Menu główne V2 – stół neuronowy**: trzech Pepe przy okrągłym stole z **ośmioma** wieżami (PEPE$WTC, PEPE$SIGNAL, PEPE$BANK, PEPE$ROI, STRATEGIES,
  MARKET NEWS, TRAINING LAB, SETTINGS). Małe logo w lewym górnym rogu, nawigacja na górze, bez paneli informacyjnych i bez przycisków na dole.
  Wieże i pasek wywołują ten sam kontroler i otwierają istniejące sekcje; Esc, fokus, klawiatura, reduced motion, pauza, Studio w górnym pasku.
  Tryb 2.5D (brak modeli 3D i riga Pepe – opisane w panelu ⓘ). Menu nie pobiera danych MT5.
* **PEPE$WTC V4** (`#/pepe-wtc`, aliasy `#/wtc`, `#/pepe-wtc`): wykres główny, Multi-Chart Workspace (dodawanie/usuwanie, niezależny TF), Indicator Manager
  tylko z warstwami bota (BB = N/A), Kronos M1/M5 (OFF/AUTO/MANUAL z realnym statusem), AI Live Zones (silnik stref, AUTO/MANUAL, filtr typów),
  **Volume Profile Auto Zones** (silnik PMW-SVP-1: POC, VAH/VAL, HVN, LVN, warstwa na wykresie), Setup Builder z R:R bez zlecenia, checklista, konsensus, MTF.
* **PEPE$SIGNAL V1** (`#/pepe-signal`, aliasy `#/signal`, `#/brain-signal`): jeden rejestr sygnałów (bot-signals + scenariusze silnika + SCALPING/HEDGING),
  filtry, lista wirtualna, wykres sygnału z Entry/SL/TP przewinięty do czasu setupu, warunki ENTRY/TRIGGER/INVALIDATION z checklisty strategii,
  narracja z faktów, tabela z sortowaniem i paginacją, oś zdarzeń, oceny modeli (stan, wersja, czas, semantyka wyniku), konsensus, metryki, MTF.
* `ChartPanel`: opcjonalna osobna warstwa `overlay` i sterowane warstwy 1.33 (bez zmian na istniejących stronach).
* Dawne panele `#/trading-intelligence` i `#/wind` działają bez zmian (menu boczne wież CULT ma do nich wpisy).
* Testy: `tests/test_ui_towers.py` (nowy), `tests/test_ui_neural_city.py` (8 wież). Raport: `docs/wdrozenie_1_36/RAPORT_WDROZENIA_PL.md`.

## 1.35.0 – PMW Quant Core (wspólny silnik obliczeń i Quant MetaModel, SHADOW)
* **Inwentaryzacja wszystkich komponentów** (`docs/quant/INVENTORY.md/.json`, `python -m masterquo quant inventory`):
  * 89 komponentów z rejestrów kodu (SH 37, rodziny 16, Trainhub 6, MM 20, lab, SI, flow, analizy); wiersze grupowe rozwinięte, 78 aliasów złożonych;
  * CatBoost = NOT_IMPLEMENTED, a `sdom` / `quant_momentum` / `renko` / `head_shoulders` / `data_grabber` / `chart_sync` = NO_SPEC (bez odtwarzania algorytmów z nazw);
  * cztery osobne miary pokrycia (katalog ≠ gotowość).
* **Kanoniczne identyfikatory i aliasy** (`quant/ids.py`): TH_RF/TH_XGB/TH_SVM rodzin = modele Trainhub; SEQ_GRU_EVENT = `mm:event_engine_dir3`.
  Jeden artefakt to jeden głos i jeden trening; na granicy koordynatora nigdy nie pojawia się `?`.
* **Snapshot danych** z QC (zamknięte świece, `available_at`, NATIVE/RESAMPLED, luki raportowane bez wypełniania, tick volume jako aktywność feedu), **kontrola kontraktów**
  (NaN/Inf/bool, jednostki, rozkłady, FUTURE_TIME, STALE, LATE_GENERATION, SYNTHETIC≠REAL) i **harmonogram DAG** (jeden właściciel, deadline, atomowa publikacja generacji).
* **Adaptery modeli spoza `all_predictions()`**: reguły SH, wskaźniki, DXY, strefy, Monte Carlo (MODEL_SIMULATED), MM (Kalman, breakout, multi-indicator, SMC, align mean, GPR),
  lab, scalp A oraz **Event GRU**. W 1.33 Event GRU nie miał żadnej ścieżki na żywo – teraz ją ma.
* **Rdzeń numeryczny, jednostki, koszty, EV** (`quant/numeric.py`, `quant/units.py`): koszty z podstawą (spread w cenach nie jest odejmowany drugi raz, nieznana prowizja ≠ zero);
  EV binarne / scenariuszowe; G=2R, L=1R, p=0,6 → 0,8R, próg 1/3.
* **EventSpec i symulator planu** (partiale, BE po potwierdzonym TP2 od następnej świecy, timeout, luka przez stop, polityka świecy niejednoznacznej ustalona z góry, koszty raz).
* **Quant MetaModel**: regresja logistyczna zdarzenia + ridge net R, walk-forward OOF z purge, kalibracja na osobnym bloku, jednokrotny test, ablacja, kryteria promocji,
  artefakty JSON z manifestem i rollbackiem; status z dowodów (`INSUFFICIENT_EVIDENCE` / `VALIDATION_FAILED` / `VALIDATED_SHADOW`).
* **Integracja**:
  * SHADOW domyślnie, zgodność wykonawcza z 1.34;
  * ASSIST tylko po walidacji i jawnym potwierdzeniu – wyłącznie wstrzymanie przez istniejący koordynator (`MODEL_QUANT_HOLD`);
  * API `/api/v1/quant/status|predictions|assessment|jobs|mode|inventory|models/*`, CLI `python -m masterquo quant …`, `37_QUANT_CORE.bat`;
  * sekcje w Koordynatorze decyzji i Centrum treningu.
* **Poprawki istniejących modułów**:
  * `evaluation/engine.py` nie traktuje już Wilsona z liczności kalibracji jako niepewności p(x) (PMW-EVAL-ENGINE-2);
  * koordynator nie traktuje czasu z przyszłości jako wieku 0 (`MODEL_REQUIRED_FUTURE_TIME`).
* Meta-model **nie był trenowany na danych rzeczywistych** (brak terminala i danych użytkownika w środowisku budowania): ledger zaczyna się zbierać po aktualizacji.
  Bez migracji bazy; nowe pliki tylko w `<dane>/quant/`.

## 1.34.2 – przycisk Studio w menu Neural City
* Przycisk **Studio** (stan i uruchamianie Pepe Data & Training Studio, 1.33) był w bocznym menu dawnego menu głównego i zniknął razem z nim.
  Teraz jest na pasku narzędzi Neural City (prawy dolny róg) oraz, jak dotąd, w górnym pasku paneli i w menu bocznym wież.
* Wykryte przez końcową regresję UI (`test_ui_pmw133`); test sprawdza teraz oba miejsca.

## 1.34.1 – poprawka instalacji na Windows
* **Błąd w 1.33.0 i 1.34.0:** instalacja zależności na Windows kończyła się „[BLAD] Instalacja pakietow nie powiodla sie”.
  * Przyczyna: statsmodels 0.15 wymaga pakietu `formulaic` (oraz `interface-meta` i `wrapt`), których nie było w
    `requirements/requirements-win.txt`. Instalacja `pip --require-hashes` zatrzymuje się na pierwszej nieprzypiętej zależności.
  * Testy w kontenerze Linux instalowały pakiety bez sprawdzania sum i błędu nie wykryły.
* **Poprawka:** `formulaic==1.2.2`, `interface-meta==2.0.1` i `wrapt==2.5.2` dodane z sumami SHA-256 kół Windows (cp312, cp313).
  Pełne domknięcie zależności sprawdzone dla Windows x64, Python 3.13 i 3.12. Bot przechodzi testy modeli z tymi wersjami.
* **Nowe narzędzie `tools/check_requirements_win.py`:** symuluje instalację każdego pliku requirements dla Windows (markery Windows,
  sumy, Python 3.13 i 3.12). `tools/build_release.py` uruchamia je przed budową paczki i przerywa ją przy błędzie.
* Bez innych zmian względem 1.34.0.

## 1.34.0 – Menu główne Neural City V7.0 i launcher JOIN THE CULT (TASK 001)
* **Menu główne Neural City** (`#/menu`): neuronowy Pepe przy holograficznym stole z siedmioma wieżami według zatwierdzonej grafiki.

  | Wieża | Otwiera istniejący panel |
  |---|---|
  | **PEPE$WTC** | Trading Intelligence |
  | **PEPE$SIGNAL** | Wind Portal |
  | **PEPE$BANK** | Lightning Tower |
  | **MARKET NEWS** | Kontekst rynku |
  | **STRATEGIES** | Strategy Lab |
  | **SETTINGS** | Ustawienia |
  | **PEPE$ROI** | Profits |

  * Wieże i górny pasek uruchamiają jeden kontroler z sekwencją SELECTED → STOP_ROTATION → PEPE_REACH → CONTACT → PORTAL → NAVIGATE.
    Esc anuluje, podwójne kliknięcie jest ignorowane, po powrocie fokus wraca na wieżę.
  * Karty Winratio / ROI (Dietz) / Equity pokazują dane bota ze znacznikiem źródła albo N/A.
  * Tryb **2.5D**: pierścienie hologramów, cząsteczki, prąd, rdzeń, gest Pepe, portal, intro z lotem przez sieć neuronów.
  * Jakość Cinematic / Balanced / Performance, pauza, ograniczony ruch.
  * Na małym ekranie pod sceną pojawia się lista wież.
* **Aliasy tras** (stare i nowe nazwy): `#/wtc`, `#/pepe-signal` (`#/brain-signal`), `#/pepe-bank` (`#/ai-agent`), `#/market-news`,
  `#/strategies`, `#/settings`, `#/pepe-roi` (`#/leaderboard`).
* **Nowe etykiety** w menu bocznym wież, tytułach okna i mapie ekranów.
* **Launcher JOIN THE CULT** (przeglądarka i okno Windows): tłem jest dostarczona grafika Pepe przemawiającego (proporcje zachowane),
  przycisk jest na dole pośrodku.
  * Animacje: fade-in, poświata, hover, kliknięcie.
  * Przejście do panelu dopiero po sprawdzeniu połączenia z silnikiem; błąd zostawia launcher z komunikatem.
  * Wszystkie dotychczasowe funkcje okna startowego pozostają.
* **Grafiki:** `tools/neural_city_assets.py`. Stare nazwy wież i przykładowe liczby z grafiki są usunięte inpaintingiem, a sumy są
  w `frontend/public/assets/neural/zrodla.json`.
* **Testy:** `tests/test_ui_neural_city.py` (9). Testy launchera i menu przeniesiono z `test_ui_cult.py`, który zostaje dla paneli wież.
* **Opis:** `docs/NEURAL_CITY_I_LAUNCHER_1_34_PL.md` (mapa tras, zmienione pliki, ograniczenia, brakujące zasoby 3D).
* **Bez zmian:** wnętrza paneli, strategie, modele, ryzyko, wykonanie, MT5, konfiguracja i baza bota. Ustawienia animacji menu są
  zapisywane tylko w przeglądarce.

## 1.33.0 – wszystkie aktualizacje: audyt i 15 rodzin modeli, wskaźniki + DXY + plany Scalp/Hedge + SVP, Data & Training Studio, architektura decyzji
* **Audyt modeli (AUD):**
  * kontrakt prognoz PMW-PRED-2: liczby skończone (nigdy bool), schematy wyników per zadanie, horyzont bez wymyślania, JSON bez NaN;
  * interwał M3 w całym łańcuchu;
  * `dxy_missing` = rzeczywista dostępność DXY;
  * Kronos REQUIRED powiązany z odciskiem ustawień;
  * ARIMA / SARIMAX dopasowywane na zwrotach skalowanych do wariancji 1, bo SARIMAX na H1 nie zbiegał.

  Lista znalezisk i napraw: `docs/AUDYT_I_NAPRAWY_MODELI.md`.
* **15 rodzin modeli (PMW-FAM-1):** TS_ARIMA, TS_SARIMAX, VOL_GARCH, MICROSTRUCTURE, PAIR_COINT, STATARB, KALMAN_LS, BREAKOUT, TH_RF, TH_SVM,
  TH_XGB, SEQ_LSTM, SEQ_GRU, RL_PPO, NLP_SENTIMENT oraz adapter SEQ_GRU_EVENT.
  * Każda ma trzy osie stanu, magazyn artefaktów (manifest, sumy, próbka inferencji), aktywację wyłącznie ręczną, rollback i role
    OFF / SHADOW / ASSIST. ASSIST wymaga walidacji APPROVED na danych REAL.
  * LSTM / GRU / PPO działają w osobnym środowisku `.venv_deep` (`34_DEEP_INSTALUJ.bat`).
  * Nowe pliki: `35_RODZINY_MODELI.bat`, `python -m masterquo families`; sekcja „Rodziny modeli 1.33” w Centrum treningu.
  * Karty modeli: `MODEL_CARDS/families/`.
* **Wskaźniki PMW-IND-1:**
  * AVWAP sesja / zdarzenie / ręczny (pasma σ, wersje kotwic);
  * spread względem sesji;
  * semiwariancja;
  * XAUUSD × DXY na zwrotach H1 bez forward-fill;
  * OFI / arkusz MT5;
  * cechy profilu sesji.

  Zakładka **Precision → XAUUSD × DXY i wskaźniki PMW** (`#/dxy`). Narzędzia agenta: `get_pmw_indicators`, `get_dxy_relation`.
* **Plany Pepe Scalp Plan / Pepe Hedge Plan (PMW-PLAN-1):** plan vs fill, SL v2 po BE, noga hedge z poziomem aktywacji; konto NETTING
  oznaczone jako „niedostępne”. Warstwy **Scalp Plan / Hedge Plan / AVWAP / SVP** są na każdym wykresie, a przełączanie nie zmienia zleceń.
* **SVP (PMW-SVP-1):**
  * profile SESSION / RANGE / VISIBLE / LIVE / FROZEN;
  * strefy MANUAL / ALGORITHM / AI z wersjami;
  * propozycja AI walidowana względem snapshotu.

  Narzędzie **Precision → SVP** (`#/svp`); agent `get_svp_profiles`.
* **Pepe Data & Training Studio:** osobna aplikacja (`PepeTrainingStudio.exe`, `36_STUDIO.bat`, przycisk **Studio** ze stanem w górnym pasku
  i w menu CULT).
  * Rejestr 72 zadań (`docs/MODEL_DATA_MATRIX.json`).
  * Eksport BOT_CACHE / MT5_DIRECT (pełna historia) pod wspólną blokadą eksportu z botem.
  * Paczka per zadanie z atomowymi etapami i sumami, test ładowania w czystym procesie.
  * Import do bota jako nieaktywny kandydat (rollback, skrzynka odbiorcza przy starcie). Studio nigdy nie składa zleceń.
* **Architektura decyzji (PMW-ARC-1):**
  * 10 kontraktów typowanych;
  * jeden Decision Coordinator dla ścieżek ACTIVE i SCALPING/HEDGING;
  * role modeli OBSERVE / ASSIST / REQUIRED (`config.decision.required_models`, domyślnie puste);
  * węzeł MODELS w drzewie decyzji ACTIVE;
  * DecisionRecord obu ścieżek (migracja 0025);
  * wspólna **atomowa rezerwacja** limitów portfela, przez co dwie ścieżki naraz nie przekroczą `max_open_positions`;
  * intencje wykonania z deduplikacją i rozliczaniem UNKNOWN z rekonsyliacji, bez ponownej wysyłki;
  * replay stary/nowy (`python -m masterquo.decision.replay`);
  * panel **Koordynator decyzji** (`#/decyzje`).

  Opis: `docs/DECISION_LOGIC.md`, `docs/ARCHITECTURE_BEFORE_AFTER.md`.
* **Konfiguracja v13:** nowe sekcje `indicators`, `families`, `decision`. Pierwszy start zostawia nietknięty plik 1.32 jako
  `data\config.v12.bak.json`, potrzebny do rollbacku (1.32 odrzuca nowe sekcje). Baza: migracja 0025 jest addytywna.
* **Nowe API:**
  * `/api/v1/indicators/*`, `/api/v1/plans/chart`, `/api/v1/svp/*`, `/api/v1/families/*`;
  * `/api/v1/studio/import|imports|status|launch`, `/api/v1/decision/status|records/{id}`.
* **Testy:** `test_integration_u1`, `test_indicators_u2`, `test_plans_svp_u3`, `test_families_u4`, `test_studio_u5`, `test_decision_arc_u6`,
  `test_ui_pmw133`, `test_config_v13`. Zaktualizowane oczekiwania: M3 w rejestrze TF, PMW-PRED-2, lista migracji, config v13.
* Bez zmian: tryby SIGNALS/PAPER/AUTO DEMO/AUTO LIVE, STOP nowych wejść, limity użytkownika, wymagania brokera, strategie S01–S12 i SH
  (gdy żaden model nie ma roli ASSIST/REQUIRED, decyzje są identyczne jak w 1.32, co potwierdza replay). Execution Lock nie wraca.

## 1.32.0 – CULT UI: launcher JOIN THE CULT, intro, Main Menu (6 wież), Lightning / Wind / Control / Strategy Lab
* **Launcher „JOIN THE CULT”** (launcher.jpg): w aplikacji Windows osobne małe okno startowe (`desktop/splash.html`, grafika wbudowana
  w EXE) z dotychczasowymi funkcjami (postęp, wybór danych, błąd + ponów, logi, zamknij) i nowym stanem **SYSTEM READY**; dopiero JOIN
  THE CULT powiększa okno do 85 % obszaru roboczego monitora i ładuje panel (`?pmw_joined=1#/menu?intro=1`). Silnik działa w tle także
  przed kliknięciem; jego awaria w trakcie oczekiwania pokazuje błąd zamiast „gotowe”. W przeglądarce: launcher na początku sesji,
  panel montowany dopiero po kliknięciu (przycisk czeka na stan bota i WebSocket).
* **Main Menu – miasto sześciu wież** (menu.jpg): Lightning, Ice (→ Precision), Wind, Control, Strategy Lab, Fire (→ Trading
  Intelligence); podgląd po najechaniu (opis + bieżąca wartość z bota), kliknięcie / Enter → przybliżenie kamery → panel; animacja
  postaci i efektów żywiołów; pasek: wynik, win rate, aktywne sygnały, equity – ze znacznikiem źródła. **Intro 6 s** (storyboard
  0,0–6,0 s), raz po JOIN, „Pomiń intro” / Esc; ograniczone animacje → bez intro i bez przybliżenia.
* **Lightning Tower – Live Signals Center**, **Wind Portal – AI Engine Core** (rodziny modeli z katalogu, macierz konsensusu bez
  uśredniania różnych jednostek, ślad decyzji, Monte Carlo nieskalibrowane, kontekst MTF, dryf; mapy przepływu modułów z dawnego menu),
  **Control Tower – Bot Management Center**, **Strategy Lab** – na istniejących endpointach bota.
* **Dane:** rodzaj każdej wartości: REAL / DEMO / DEMO · symulator / brak danych / nieaktualne / błąd synchronizacji; dane rynkowe na
  symulatorze nigdy jako REAL; brak łącza z botem → pasek „nieaktualne”. Bez wymyślonych ROI, win ratio, sald ani skuteczności AI.
* **Zapis ustawień (Control Tower):** progi CONFIRMED / EARLY, filtry (makro, konflikt D1, max spread), wybór strategii, limity ryzyka,
  szablon wiadomości Telegram (walidowane zmienne, podgląd na ostatnim sygnale albo oznaczonym przykładzie, zawsze „Analysis only –
  not an order.”), przełączniki wiadomości, **presety strategii** (`data/presets/strategy.json`, tylko pola sterowania strategią).
  Nowe API: `/api/v1/system/resources` (CPU/RAM komputera bota), `/api/v1/telegram/preview`, szablon w `/api/v1/telegram/test`,
  `/api/v1/presets/strategy` (lista, zapis, wczytanie, reset), `/api/v1/telegram/template` (GET / PUT). Szablon i presety są w
  osobnych plikach (`data/telegram/signal_template.json`, `data/presets/strategy.json`) – `config.json` bez nowych kluczy, więc 1.31
  nadal go czyta po powrocie (sprawdzone).
* **Usunięte:** menu trzech wież 3D z 1.26 (three.js wypada z zależności); widoki Precision / Dyscypline / Profits bez zmian.
* **Testy:** `tests/test_ui_cult.py` (launcher, intro, 6 wież, nawigacja, znaczniki danych, panele w 3 szerokościach, zapis konfiguracji,
  potwierdzenia, ograniczone animacje, jeden WebSocket), `tests/test_cult_backend.py`, testy okna w `desktop/desktop_test.go`;
  zaktualizowane `test_ui_pages`, `test_ui_wizard`, `test_ui_interface_129`.
* Bez zmian: strategie, progi domyślne, ryzyko, koszty, tryby SIGNALS/PAPER/AUTO DEMO/AUTO LIVE, STOP, TP/SL, modele, MT5, Telegram.

## 1.31.0 – Kronos AI Forecast (przetrenowany Kronos-small, lokalnie, SHADOW)
* **Model:** NeoQuasar/Kronos-small + Kronos-Tokenizer-base (oficjalne wagi, przypięte rewizje `901c26c…` / `0e01173…`), kod Kronos (MIT)
  w `backend/kronos_runtime/vendor/kronos` – zmieniony tylko import (własna przestrzeń nazw zamiast ogólnego `model`). Bez treningu w bocie.
* **Osobne środowisko i proces:** `.venv_kronos` (PyTorch 2.14.1 CPU z PyPI, pakiety tylko z sumami SHA-256 –
  `requirements/requirements-kronos-win.txt`), proces `kronos_runtime.worker`: model ładowany raz, tryb eval, bez gradientów, GPU tylko
  gdy CUDA działa (test), inaczej CPU z przyczyną. Instalacja: przycisk **Zainstaluj model Kronos** albo `33_KRONOS_INSTALUJ.bat`
  (`cu126`/`cu128` dla GPU). Wagi sprawdzane z metadanymi źródła (LFS sha256 / git blob sha1), tylko safetensors, manifest z sumami;
  **Sprawdź instalację** – sumy, ładowanie, prognoza testowa i porównanie z wynikiem autorów. Po instalacji działa offline.
* **Dane:** zamknięte świece z istniejącego mostu MT5 (bez drugiego połączenia), XAUUSD i BTC przez mapowanie symboli (BTC dopiero po
  potwierdzeniu), M1–H1 (domyślnie M5 i M15, M30 natywnie). Kontrola jakości (kolejność, duplikaty, geometria OHLC, braki, luki w sesji,
  świeżość), kalendarz sesji mierzony na świecach brokera (przerwy dzienne i weekendy) do czasów przyszłych świec – niepewny kalendarz
  wstrzymuje prognozę. Wolumen: real_volume / tick_volume (oznaczony: to nie obrót) / bez wolumenu; amount = syntetyczne przybliżenie.
* **Serwis:** prognoza po nowej zamkniętej świecy albo na żądanie, kolejka z deduplikacją i limitem, limit czasu z restartem procesu,
  stan i przyczyna zamiast pozornej prognozy; prognozy zapisywane przed wynikiem i rozliczane prawdziwymi świecami (MAE vs „ostatnia
  cena”, kierunek); osobno dane rzeczywiste i syntetyczne.
* **Integracja:** kontrakt PMW-PRED-1 (REGRESSION, jednostka cena, kalibracja „nie dotyczy”), rejestr modeli, osobny kontekst w ocenie
  SCALPING/HEDGING (zgodność/konflikt z innymi modelami i strukturą, bez uśredniania). Domyślnie **OBSERVE** – bez wpływu na decyzje;
  **REQUIRED** tylko po pozytywnej walidacji walk-forward na danych rzeczywistych i potwierdzeniu – może wyłącznie wstrzymać setup.
* **Walidacja walk-forward** na świecach użytkownika (DEV/TEST chronologicznie, horyzonty bez nakładania, odniesienia: ostatnia cena
  i momentum, test dwumianowy, zastrzeżenie o możliwym nakładaniu z pretreningiem).
* **Panel „Kronos AI Forecast”** (Wykresy bota), instrukcja `INSTRUKCJA_KRONOS.md`, raport `docs/KRONOS_RAPORT_WDROZENIA.md`, migracja
  bazy 0024 (tabela `kronos_forecasts`, addytywnie), ustawienia w osobnym pliku `data/kronos/settings.json` (config.json bez zmian).
* Bez zmian: strategie, progi, ryzyko, koszty, tryby, STOP, TP/SL, pozostałe modele.

## 1.30.1 – poprawki po pełnej regresji: panel Neural Cyberpunk bez zawieszania (bez GPU), FFT bez fałszywego TIMEOUT po starcie
* **Naprawa:** animowany „mózg” na pulpicie Neural Cyberpunk przerysowywał statyczną warstwę (ok. 700 linii, każda z osobnym
  rozmyciem `shadowBlur` w trybie `lighter`) przy każdym odświeżeniu rejestru modeli, czyli co kilka sekund. Bez akceleracji GPU
  (rysowanie programowe, np. Windows VPS / maszyna wirtualna, przeglądarka testowa) każde takie przerysowanie blokowało całe okno
  na ok. 10 s, a przy 1440 px panel otwierał się po 20–40 s. Teraz warstwa statyczna rysuje się tylko przy zmianie rozmiaru,
  a poświata powstaje w jednym przejściu rozmycia; dane z rejestru i tryb są czytane bez restartu animacji. Pomiar w Chromium bez
  GPU (1440×900): otwarcie panelu ok. 1 s zamiast 20–40 s, płynna animacja (ok. 58 klatek/s zamiast ok. 2). Wygląd bez zmian.
  Usterka była już w 1.17–1.30.0; wykrył ją test `test_nc_panel` w pełnej regresji 1.30.
* **Naprawa:** pierwsze obliczenie FFT po starcie programu wliczało do limitu 10 s jednorazowe ładowanie biblioteki `scipy.signal`
  (ok. 1–1,5 s, a gdy cały program dopiero startuje – ponad 10 s). Karta „Analiza sygnału → FFT” pokazywała wtedy „TIMEOUT > 10s”
  aż do następnej świecy. Wątek analityki ładuje teraz biblioteki raz, przed pierwszym obliczeniem; limit dotyczy samego obliczenia
  (nowy test `test_library_load_is_not_counted_in_the_timeout`; wykryte przez `test_ui_analytics` w pełnej regresji 1.30).
* Bez zmian w logice bota, strategiach, ryzyku, trybach, danych i API.

## 1.30.0 – system licencji usunięty (na Twoją prośbę)
* **Program działa bez klucza** – usunięte: strażnik licencji przed nowymi wejściami (S01–S12, ręczne, SCALPING/HEDGING), blokada
  powiadomień Telegram o nowych sygnałach, okno KEY FOR MAGIC, License Manager (OWNER), obszar „Licencje”, oznaczenia OWNER/CLIENT
  (pasek stanu, tytuł okna i aplikacji Windows), API `/api/v1/license*` i `/api/v1/owner/*`, moduł `backend/masterquo/license`,
  serwer licencji `license_server/`, `edition.json`, narzędzie wydania wersji CLIENT (`tools/stamp_client_edition.py`,
  `PRZYGOTUJ_PACZKE_KLIENTA.bat`) i zależności Windows dodane tylko dla licencji (`cryptography`, `cffi`, `pycparser`).
* Jedna wersja programu: paczki `PepeMarketWizard_DESKTOP_1_30_x.zip` (aplikacja Windows) i `PepeMarketWizard_1_30_x.zip` (folder).
* Dawny link `#/licencje` otwiera Ustawienia. Pliki licencji pozostałe w folderze danych z 1.27–1.29 (`license_owner.json`,
  `license_owner_key.*`, token licencji) nie są używane ani usuwane automatycznie – można je skasować.
* Bez zmian: strategie, progi, ryzyko, koszty, tryby SIGNALS / PAPER / AUTO DEMO / AUTO LIVE, STOP, wykresy i strefy 1.29, interfejs
  w stylu wież. System licencji 1.27–1.29 pozostaje w historii repozytorium.

## 1.29.0 – licencje bez logowania, wykresy z własnymi ustawieniami i „Wyznacz strefy”, jeden interfejs w stylu wież
Realizacja pakietu aktualizacji (CLAUDE_WDROZENIE.md). Opis, procedury i blokady: `docs/AKTUALIZACJA_1_29_PL.md`; wyniki testów:
`release/RAPORT_KONCOWY.md`.
* **Licencje 1.1 (serwer) / OWNER bez logowania:** klucz urządzenia Ed25519 (Windows DPAPI), podpisane żądania administracyjne
  (PMW-ADMIN-v1, ±120 s, trwała ochrona przed powtórzeniem), parowanie poleceniem `admin-keys add` w powłoce serwera, rotacja
  i odwołanie kluczy, `backup-db`; License Manager z kreatorem parowania; okresy 72h / 7d / 31d (24h – zaawansowane); hasło
  administratora opcjonalne (tylko dla OWNER < 1.29). Adres serwera: tylko HTTPS (localhost do testów), przekierowania odrzucane.
* **Wykresy:** „Wyznacz strefy” w głównym obszarze wykresów (M1 + M5 + M15 domyślnie, pojedynczo, M30, wszystkie cztery), LIVE,
  postęp, błąd, ostatnie udane przeliczenie, stan źródła; strefy tylko na wykresie tego samego instrumentu, symbolu i interwału.
  Własne ustawienia każdego wykresu (kolory, siatka, tekst, wolumen, strefa czasu, kolor i krycie typów stref, etykiety, szablony,
  reset) zapamiętane lokalnie; menu warstw FVG / OB / popyt-podaż / S/R / płynność (hipoteza) / etykiety – także na stronie Strefy.
* **Interfejs:** motyw „trzy wieże” (domyślny; własne kolory nienaruszone), menu według obszarów Precision / Dyscypline / Profits /
  Modele i trening / Ustawienia i diagnostyka / Licencje (tylko OWNER), stan na każdym ekranie (instrument, symbol, MT5, czas ostatnich
  danych, DEMO / LIVE / SYNTETYCZNE, tryb, STOP, edycja i licencja), edycja w tytule okna i aplikacji Windows, mapa ekranów
  (stare linki działają), `prefers-reduced-motion`, fokus klawiatury.
* **Wydania:** build bez `.git` (jawna lista z manifestu), `tools/verify_release.py` (ZIP-slip, sumy, pliki zabronione, sekrety),
  `tools/migration_check.py` (1.28 → 1.29 i powrót na kopiach danych). Paczka CLIENT: **BLOKADA** do czasu prawdziwego serwera HTTPS.
* Bez zmian: strategie, progi, ryzyko, koszty, tryby SIGNALS / PAPER / AUTO DEMO / AUTO LIVE, STOP; Execution Lock nie wraca.
* Niepodpisane cyfrowo (brak certyfikatu). Nie sprawdzono: Windows, prawdziwy MT5, publiczny serwer licencji.

## 1.28.0 – Strefy rynkowe M1/M5/M15/M30, rejestr modeli, pipeline MT5 → trening → bot (Centrum treningu)
Pełny opis, audyt, rejestr modeli, instrukcje, wyniki testów i luki: `docs/STREFY_MODELE_TRENING_1_28_PL.md`.
* **Strefy rynkowe** (Wykresy → Strefy rynkowe): instrument XAUUSD / BTC, niezależny wybór M1/M5/M15/M30 (domyślnie wszystkie cztery),
  „Wyznacz strefy teraz”, „Aktualizacja na żywo” (przeliczenie interwału dopiero po zamknięciu jego świecy; dotknięcia z ceny na żywo
  wstępne), „Zatrzymaj”, status źródła na interwał (połączone / dane nieaktualne / brak danych / błąd), czas danych i przeliczenia, postęp.
  Silnik PMW-MZ-1: S/R ze swingów, popyt/podaż, FVG, order blocks (jawna reguła BOS), równe szczyty/dołki jako płynność WNIOSKOWANA z OHLC,
  konfluencja interwałów; pełny rekord strefy (id, granice, czas źródła i wykrywalności, kierunek, stan wstępna/aktywna/testowana/
  unieważniona/wygasła, niezależne testy, powód, reguła unieważnienia, jakość 0–100 ze składnikami – nie prawdopodobieństwo, wersja);
  brak danych z przyszłości, historia „na chwilę”, łączenie z zachowaniem pochodzenia, limit widocznych stref, parametry skalowane ATR
  i profilem złoto/BTC; odporność na wielokrotny klik, rozłączenie, zmianę instrumentu; starszy wynik nie nadpisuje nowszego.
* **Eksport MT5** (`marketdata/`): historyczny i przyrostowy, partiami z ponawianiem i wznawianiem, deduplikacja (instrument, TF, czas),
  UTC z konwencją DST serwera, tylko zamknięte świece, Parquet + CSV + manifest (parametry, źródło, liczności, zakresy, wersja schematu,
  SHA-256), kontrola kolejności / duplikatów / OHLC, luki sesji odróżnione od braków danych, raport realnej historii; koszty: spread ze
  świec (zmierzony), prowizja tylko z historii transakcji, poślizg = założenie; historycznego bid/ask nie rekonstruujemy. Import danych
  z innej maszyny z weryfikacją sum (MT5 na innym komputerze).
* **Pipeline i Centrum treningu** (Modele i trening → Centrum treningu, `32_CENTRUM_TRENINGU.bat`, `python -m masterquo trainhub`):
  wspólne cechy dla treningu i inferencji, wyższe TF dołączane od zamknięcia, etykiety po kosztach, walk-forward z purgingiem i embargo,
  nietknięty zbiór końcowy, model bazowy, kalibracja, stabilność, ocena po kosztach; modele bazowy / regresja logistyczna / gradient
  boosting / XGBoost osobno dla XAUUSD i BTC; paczki z manifestem; trening w osobnym procesie (kolejka, postęp, logi, anulowanie);
  porównanie wersji, eksport datasetu i paczki; aktywacja wyłącznie ręczna po teście zgodności i predykcji, rollback.
* **Modele**: wspólny kontrakt predykcji PMW-PRED-1 (stan + powód zamiast wartości przy błędzie), rejestr 54 modułów z kategorią i
  stanem na żywo (gotowy / niewytrenowany / trening / błąd / niezgodny / wyłączony), jawne mapowanie na role strategii, jedna grupa
  korelacji = jeden głos, wagi z walidacji rozwojowej; nowe modele = OBSERVATION (nie głosują w strategiach).
* Naprawione w trakcie: dane z symulatora pobierane przez bridge mogły zostać oznaczone jako rzeczywiste (flaga odczytywana jako metoda);
  wspólne połączenie SQLite kolejki zadań używane z dwóch wątków (błąd pod obciążeniem) – jedna blokada; istniejący wyścig w teście
  biblioteki formacji (Structure Intelligence).
* Testy: regresja 83 moduły / 988 testów + 14 modułów UI / 92 testy (Chromium) – szczegóły i poprawki w dokumencie 1.28 §6.
* Zależność Windows: `pyarrow` 26.0.0 (z hashami) – zapis Parquet.
* Bez zmian: strategie, progi, system ryzyka, tryby SIGNALS / PAPER / AUTO DEMO / AUTO LIVE, STOP, licencje; Execution Lock nie wraca.
* Wszystkie treningi w tym środowisku: dane SYNTETYCZNE (symulator). Brak testu z prawdziwym MT5 i Windows; brak dowodu przewagi modeli.

## 1.27.0 – system licencji v1 (OWNER / CLIENT) i sygnały BUY/SELL wszystkich strategii
Realizacja paczki „PepeMarketWizard License System v1.0” (na Twoje polecenie – licencje usunięte w 1.9 wracają w nowej formie) oraz
„niech wszystkie strategie mogą nadawać sygnały buy/sell”. Pełny opis, audyt, uruchomienie i ograniczenia: `docs/LICENCJE_SYSTEM_1_27_PL.md`.
* **Sygnały BUY/SELL wszystkich strategii:** S01–S12 jak dotąd (oba kierunki, także skaner innych rynków); nowe źródła tych samych
  sygnałów bota: SCALPING i HEDGING (READY), Range→Sweep→Retest (READY_SHADOW) i Double Retest v2 (RESEARCH_SETUP_COMPLETE) – BUY i
  SELL, walidacja wobec bieżącej ceny, jeden sygnał na setup, śledzenie WIN/LOSS/TIMEOUT, WebSocket, Telegram; strategie SHADOW /
  badawcze oznaczone jako niezweryfikowane; przełączniki `signals.strategy_sources`. Sygnał nigdy nie składa zlecenia.
* **Serwer licencji** (`license_server/`, osobna paczka): FastAPI + SQLite, klucze 24h / 72h / 7d / 31d pokazywane raz (w bazie tylko
  HMAC), okres od pierwszej aktywacji (UTC), wiązanie z urządzeniem, `DEVICE_MISMATCH`, cofnięcie, reset HWID tylko przez
  administratora, podpisane Ed25519 odpowiedzi z nonce, logowanie administratora (scrypt, sesje bearer), limity zapytań, dziennik
  audytu bez kluczy i tokenów, CLI (init-keys / hash-password / new-pepper / serve / create-license), przykłady Caddy i systemd.
* **OWNER EDITION** (Twoje paczki `PepeMarketWizard_OWNER_1_27_0.zip`, `PepeMarketWizard_DESKTOP_OWNER_1_27_0.zip`): bot bez bramki
  licencji + **License Manager** (Ustawienia → Licencje): logowanie do serwera, generowanie kluczy, lista, cofnięcie, reset HWID,
  audyt. Hasło nie jest zapisywane.
* **CLIENT EDITION** (paczki dla klientów z `PRZYGOTUJ_PACZKE_KLIENTA.bat` / `tools/stamp_client_edition.py` – adres i klucz
  publiczny Twojego serwera): okno **KEY FOR MAGIC** (bez logowania klienta), jeden `LicenseGuard`: walidacja online przy starcie, co
  5 min i tuż przed każdym nowym wejściem (S01–S12, ręczne, SCALPING/HEDGING; także PAPER), bez okresu offline; bez ważnej licencji
  brak nowych wejść i powiadomień o nowych sygnałach – **otwarte pozycje nie są zamykane**, zarządzanie nimi i noga hedge działają.
  Token urządzenia w DPAPI, klucz licencji nie jest zapisywany; odcisk urządzenia: MachineGuid + SMBIOS UUID + wolumin (bez MAC).
* Zależności Windows: `cryptography`, `cffi`, `pycparser` (z hashami) – weryfikacja podpisów po stronie klienta.
* Bez zmian: strategie i ich progi, modele, tryby SIGNALS / PAPER / AUTO DEMO / AUTO LIVE, STOP, limity; Execution Lock nie wraca
  (licencja to jawna bramka edycji CLIENT, widoczna w panelu – w OWNER nie blokuje niczego).
* Testy: `test_license_server` 10/10, `test_license_client` 12/12, `test_license_build` 5/5, `test_ui_license` 2/2,
  `test_strategy_signals` 6/6 (pozostałe uruchomione testy: `docs/LICENCJE_SYSTEM_1_27_PL.md` §8). Nie wykonano: uruchomienia na
  Windows i z prawdziwym MT5, wdrożenia serwera na VPS, testów bezpieczeństwa serwera.

## 1.26.0 – menu główne „trzy wieże” (Precision / Dyscypline / Profits) i mapy przepływu modeli
Realizacja specyfikacji „PEPEMARKETWIZARD — NEURO MAGIC CYBERPUNK”. Opis, kontrole, zrzuty i luki: `docs/MENU_WIEZE_1_26_PL.md`.
* **Menu główne (`#/menu`, pierwszy start):** logo Pepe-czarodzieja (powrót do menu), górny pasek z instrumentem, stanem MT5, świeżością
  danych i trybem bota (z prawdziwych danych; na symulatorze „SYMULATOR”, nigdy „LIVE”), tło – wieża z fioletowymi błyskawicami z
  warstwą na żywo (parallax, mgła, pył, błyskawice, światło kursora w kolorze wieży; statyczne przy ograniczonych animacjach).
* **Trzy wieże 3D (three.js, geometria proceduralna):** Precision (obserwatorium, cyjan/fiolet, kryształ, pierścienie pomiarowe),
  Dyscypline (cytadela, ametyst/szmaragd, runy, brama energii), Profits (skarbiec, złoto/szmaragd, kula energii, orbitujące cząstki).
  Przyciski HTML przy wieżach (klawiatura, dotyk, czytnik ekranu), ruch kamery + portal ~0,56 s, opis wieży. **Kliknięcie wieży
  wyłącznie nawiguje.** Bez WebGL (albo `#/menu?webgl=0`) – te same przyciski z rysunkami wież; tak samo
  automatycznie, gdy scena rysuje się poniżej 5 kl./s przy najniższej rozdzielczości (renderowanie bez GPU – bot potrzebuje procesora;
  wymuszenie 3D: `#/menu?webgl=1`). FPS zmierzony w teście na rendererze programowym SwiftShader: 0,7–1,2 kl./s (bez GPU; na GPU nie mierzono). Ograniczone animacje w systemie = statyczna scena rysowana tylko przy zmianie.
  Adaptacyjna rozdzielczość, pauza
  w tle, zwalnianie zasobów.
* **Mapy przepływu modeli po bokach menu:** dane i analizy (MT5 → świece 7 interwałów → jakość danych → moduły) oraz modele z rejestru
  → SCALPING / HEDGING / drzewo decyzji → decyzje. Impulsy wyłącznie z rzeczywistych zdarzeń jedynego WebSocket, kolor = stan,
  offline = brak impulsów; tooltip, szczegóły, lista modułów, filtry, obrót i zoom. Nowy endpoint `GET /api/v1/telemetry` (stan
  tematów magistrali zdarzeń, rejestr modeli, SH, drzewo decyzji – tylko odczyt).
* **Widoki z własnym tłem:** Precision (wykresy świecowe z MT5, interwały, siatka, warstwy analiz, notowanie, reżim per interwał,
  strefy), Dyscypline (setupy i sygnały: stany obserwacja / formujący się / gotowy / sygnał aktywny / unieważniony / wygasły /
  zakończony, warunki, trigger, unieważnienie, wejście/SL/TP, sprzeczności modeli, ryzyko, wykres; wybór w adresie; „ocena setupu”
  nigdy jako prawdopodobieństwo), Profits (saldo, equity, wynik otwartych, zrealizowany netto, ROI z metodą, win rate W/L/BE,
  prowizje/swapy, wpłaty i wypłaty jako „nie zysk”, obsunięcie tylko z krzywej, deale MT5 vs transakcje, krzywa kapitału, historia,
  porównania ścieżek / strategii / instrumentów / miesięcy). Statystyki: nowe pola `deposits`, `withdrawals`, `per_symbol`.
* **Zasoby:** jedna konfiguracja `frontend/src/features/wizard/assets.ts` (plik → przeznaczenie → pochodzenie), pliki w
  `frontend/public/assets/wizard/`, generator `tools/wizard_assets.py`.
* Dotychczasowe widoki (terminal, pulpit, AI Neural Lab, Centrum sterowania) bez zmian – dostępne z paska terminala (sekcja „Wieże”
  prowadzi do menu) i ze stopki nowych widoków. Bez zmian: tryby SIGNALS / PAPER / AUTO DEMO / AUTO LIVE, STOP nowych wejść, limity
  użytkownika; Execution Lock nie wraca (decyzja z 1.24).
* Testy: nowy `tests/test_ui_wizard.py` (Chromium + WebGL SwiftShader); `test_ui_pages` / `test_ui_analytics` – pierwszy start to
  teraz menu. Wyniki: `docs/MENU_WIEZE_1_26_PL.md` §6.

## 1.25.0 – eksport MT5 → trening, Monte Carlo ścieżek, strefy po restarcie, scenariusz XAUUSD- 2,5–10 USD
Realizacja `PepeMarketWizard_PROMPT_MONTE_CARLO_STREFY_STRATEGIA.md`; audyt: `docs/AUDYT_MC_STREFY_EKSPORT_PL.md`; raport:
`docs/RAPORT_MC_STREFY_STRATEGIA_1_25_PL.md`; punkt powrotu: commit `a10d97a` (1.24.1).
* **Eksport MT5 do treningu (priorytet 4A):** plik stanu `EXPORT_STATUS.json` (W TOKU / UKOŃCZONY / BŁĄD / PRZERWANY), zapis atomowy
  wszystkich plików, `source_metadata.json` usuwany na starcie i zapisywany na końcu – **przerwany lub nieudany eksport nigdy nie wygląda
  na kompletny**; wznowienie po uszkodzonej partii (partia pobierana ponownie zamiast błędu `JSONDecodeError`); kolumna `real_volume`
  (gdy broker ją podaje; `tick_volume` to liczba ticków, nie wolumen giełdowy); opcjonalne ticki Bid/Ask (`--ticks-days`, partie
  godzinowe, ticki o tym samym czasie zachowane); zakres dat `--from/--to`; sprawdzenie konwencji czasu serwera (DST) na historii,
  nie tylko na dzisiejszym offsecie; czytelne błędy (brak terminala, symbolu, uprawnień, miejsca).
* **Gotowość danych per model:** `MODEL_DATA_READINESS.json` w każdym eksporcie – model → wymagane interwały / ticki → plik → wiersze →
  `GOTOWE / BRAK_DANYCH / NIEZGODNY_FORMAT / NIEKOMPLETNY_EKSPORT`. Runner treningu może użyć gotowego eksportu
  (`--dataset-xauusd`, `--dataset-btc`, w panelu wybór eksportu).
* **Panel AI Neural Lab → Trening:** karta „Eksportuj dane z MT5” (symbol, okres lub daty, interwały, ticki, postęp, przerwanie, tabela
  gotowości modeli, „Użyj do treningu”). Eksport działa jako osobny proces tylko do odczytu (bez zleceń).
* **Monte Carlo ścieżek (nowe, `masterquo/montecarlo`):** losowanie całych świec (IID / blokowe / warunkowane reżimem ATR i godziną
  sesji), tylko dane sprzed chwili oceny, zdarzenia „TP przed SL w horyzoncie” po stronie Bid/Ask, świeca dotykająca TP i SL =
  przedział ostrożny–optymistyczny (kolejność nie jest zgadywana; ticki rozstrzygają, gdy są), błąd z liczby ścieżek. Walidacja
  walk-forward z embargo względem klimatologii (Brier, log loss, krzywa kalibracji, CI bootstrap), kalibrator izotoniczny, rejestr z
  rollbackiem; aktywny tylko po walidacji na Twoich danych z przewagą. Bez kalibracji wynik jest opisany jako „prawdopodobieństwo w
  modelu”. API `/api/v1/montecarlo/*`, CLI `python -m masterquo montecarlo validate|status|rollback`, zadanie runnera `monte_carlo`.
* **Strefy High/Low M5/M15:** po restarcie ostatnia mapa jest odtwarzana z bazy i oznaczona `RESTORED` + `STALE` do pierwszego
  przeliczenia (nie potwierdza decyzji).
* **Scenariusz SCALPING XAUUSD- 2,5–10 USD:** dla poziomów 2,5 / 3 / 5 (TP1–TP3, zlecenia częściowe) oraz 7,5 / 10 (tylko analiza)
  osobno: ruch ceny, wolumen części na siatce brokera, wynik w walucie rachunku z wartości ticka terminala, spread, prowizja (nieznana =
  „nieznana”, wynik netto N/A – nigdy 0), poślizg, P(TP przed SL) z Monte Carlo (ostrożnie–optymistycznie, niejednoznaczne, błąd,
  skalibrowane tylko po walidacji), BE po POTWIERDZONYM TP2 = wejście + koszty, modele – każdy ze swoim zdarzeniem, **bez łączenia
  i uśredniania procentów**, powód braku zlecenia. Karta w Trading Intelligence, API `GET /api/v1/sh/scenario`. TP3 SCALPING XAUUSD
  można wybrać z 5 / 7,5 / 10 USD (domyślnie 5 – bez zmian); progi XAUUSD nie są kopiowane na BTC. Zlecenia składa wyłącznie istniejący
  cykl SCALPING (tryb, STOP, limity, broker) – nie powstał drugi system handlu.
* Bez zmian: tryby SIGNALS / PAPER / AUTO DEMO / AUTO LIVE, STOP nowych wejść, limity użytkownika; Execution Lock nie wraca.
* **Nie wykonano w tym środowisku:** eksportu z Twojego MT5, treningu na Twojej historii, testu rachunku DEMO, uruchomienia na Windows –
  wszystkie wyniki liczbowe w raporcie pochodzą z symulatora (dane `SYNTHETIC_TEST`).

## 1.24.1 – poprawka folderu aplikacji Windows

* **Błąd (zgłoszony):** w folderze `PepeMarketWizard_Desktop` stary launcher `PepeMarketWizard.exe` i instalatory `01_INSTALUJ.bat`,
  `INSTALUJ_TRENING.bat`, `00_TRENING_START.bat` kończyły się komunikatem „Niekompletny folder programu – brak: MANIFEST_SHA256.txt”.
  Paczka aplikacji ma teraz `MANIFEST_SHA256.txt` (jak paczka klienta) – test sprawdza listy plików launchera i instalatorów.
* Instalatory `.bat` w folderze aplikacji używają **Pythona z paczki** (`runtime\python`) – bez instalowania Pythona w systemie
  (Python w systemie pozostaje zapasowym wyborem; klasyczna paczka bez zmian).
* `.bat`, launcher i aplikacja pracują na **tych samych danych**: w folderze aplikacji `%LOCALAPPDATA%\PepeMarketWizard\data`
  (przy `portable.txt` – folder programu), wcześniej skrypty zapisywałyby trening do `data\` w folderze programu, niewidocznego dla aplikacji.
* Launcher w folderze aplikacji wyjaśnia, że bota uruchamia się przez `PepeMarketWizardDesktop.exe`.
* Poprawka 1.24.0 (przed wydaniem): eksport na symulatorze był oznaczany `REAL_USER_DATA` (regresja wycofania Execution Lock) – naprawione.

## 1.24.0 – PepeMarketWizard Desktop: aplikacja Windows, trzy panele na danych, Telegram EN+ZH, Execution Lock wycofany
* **Aplikacja Windows `PepeMarketWizardDesktop.exe`** (Go + WebView2, `desktop/`): własne okno, wbudowany Python (NuGet, hash),
  zależności instalowane przy pierwszym starcie (`--require-hashes`, wariant OFFLINE z kołami), dane w `%LOCALAPPDATA%\PepeMarketWizard`
  (tryb przenośny `portable.txt`), import poprzedniej instalacji (kopia; AUTO → PAPER), kopia danych przed nową wersją, nadzór silnika
  (podłączenie zamiast duplikatu, restart po awarii z limitem, restart na żądanie, Job Object), pytanie przy zamykaniu / praca w tle /
  zakończenie, ikona przy zegarze, autostart HKCU tylko po włączeniu. Budowa: `tools/build_desktop.py`; opis: `docs/DESKTOP_ARCHITEKTURA.md`.
  **Nie uruchomiono jeszcze na rzeczywistym Windows** (kompilacja krzyżowa i testy na Linuksie).
* **Trading Intelligence / AI Neural Lab / Centrum sterowania** na danych silnika i MT5 (wg zatwierdzonych makiet): rachunek i ROI
  (modified Dietz), 1/4/6 wykresów z zapisem układu, Signal Intelligence z osobnymi odpowiedziami „brak sygnału” / „brak zlecenia”,
  rejestr modeli, trening, walidacja i wdrożenia, grafika sieci oznaczona jako przykład, tryby z konsekwencjami i potwierdzeniem
  rachunku, STOP, ścieżka główna, ryzyko i koszty, praca aplikacji, diagnostyka, przełącznik XAUUSD-/BTC, ustawienia „Wygląd”.
* **Telegram:** wiadomości dwujęzyczne EN + 中文 (lub jeden język), sygnały, otwarcie / zamknięcie pozycji (ścieżka główna i SH),
  dzienne podsumowanie, rzeczywisty stan połączenia i wiadomość testowa; błąd wysyłki nigdy nie wpływa na handel.
* **Bramki strategii (`docs/STRATEGIE_BRAMKI_DESKTOP.md`):** wybór AUTO do wykonania tylko spośród strategii z prawem handlu
  (S11/S12 „tylko sygnały” nie blokują już setupu strategii dopuszczonej); bramka AI (VETO) bez klucza = „nie wymagane” na każdym
  etapie; SH AUTO DEMO bez skalibrowanego modelu (AUTO LIVE nadal wymaga modelu i walidacji). Porównanie przed/po w dokumencie.
* **Poprawka:** okno Ustawień wysyłało tryb wykonania przy zapisie (od DK1 → błąd 400); teraz go nie wysyła, a backend pomija
  niezmienione wartości.
Realizacja `docs/desktop_handoff/00_PROMPT_WYKONAWCZY.md`; audyt: `docs/DESKTOP_AUDIT.md`; punkt powrotu: commit `ba7a5d5`.
* **Execution Lock wycofany (decyzja użytkownika).** Worker MT5 przekazuje terminal bez proxy blokującego; z gateway, menedżera pozycji,
  ręcznego padu, bramki trybu i SH usunięto warunek `EXECUTION_LOCKED`; trasa z frazą odblokowania zwraca 410. Nie ma nowej blokady pod
  inną nazwą. Pozostają: tryb (SIGNALS / PAPER / AUTO_DEMO / AUTO_LIVE), potwierdzony rachunek, STOP nowych wejść, limity ryzyka, świeżość
  danych, uzgodnienie z terminalem, idempotencja, serializacja przez worker.
* **Migracja konfiguracji v12:** pola `lock` usunięte; zapisany tryb AUTO, który stara blokada wstrzymywała, → PAPER + komunikat
  (`execution.mode_note`) – brak cichego uruchomienia zleceń; tryb AUTO odblokowany wcześniej przez użytkownika działa dalej. Kopia:
  `config.v11.bak.json`. Tryb zmienia się wyłącznie przez `POST /api/v1/mode` (zapis konfiguracji z `execution.mode` → 400).
* **SCALPING / HEDGING:** bezwarunkowa odmowa AUTO_LIVE zastąpiona warunkiem: rachunek REAL + zaliczona walidacja strategii na historii
  klienta (REAL_USER_DATA, znana prowizja, n ≥ 30, dodatni wynik po kosztach) – inaczej jawny powód `SH_LIVE_WYMAGA_WALIDACJI`.
  Zarządzanie otwartymi planami nie jest blokowane regułami trybu (wymaga terminala i tego samego rachunku). Uzgadnianie z terminalem,
  odzyskiwanie po restarcie i liczenie obcych pozycji obejmują teraz AUTO_DEMO i AUTO_LIVE.
* Panel: zamiast stanu blokady – rzeczywisty tryb wykonania i STOP z backendu (stary monitor, Neural Cyberpunk, nowy shell).

## 1.23.0 – Nowy monitor PMW (etap 1): Trading Intelligence / AI Neural Lab / System Control Center
Paczka klienta wydana na prośbę użytkownika po etapie 1. Nowy monitor zawiera szkielet (shell, nagłówek ze stanem z backendu, puste
sekcje oznaczone „nie zintegrowane”); integracja paneli – etapy 2–4. Backend, strategia, modele, ryzyko i wykonanie bez zmian
względem 1.22.0 (zmienione tylko numery wersji i launcher przebudowany z nowym numerem).
* **Poprawka (stary monitor, strona „Formacje”):** po walidacji biblioteki link do raportu mógł się nie pojawić – panel kończył
  odpytywanie tuż przed zapisem raportu; teraz czeka na raport (najwyżej ok. 10 s).
* **Etap 0 – audyt:** `docs/PEPE_UI_AUDIT.md`, `docs/PEPE_UI_API_MAP.md`, `docs/PEPE_UI_IMPLEMENTATION_PLAN.md`,
  `docs/PEPE_UI_TEST_PLAN.md` (specyfikacja: `docs/PEPE_UI_IMPLEMENTATION_SPEC.md`).
* **Etap 1 – szkielet:** nowe trasy `#/trading-intelligence`, `#/ai-neural-lab`, `#/system-control` w osobnym shellu
  (`frontend/src/features/`): sidebar stały i zwijany, nagłówek ze środowiskiem (LIVE / DEMO / SYNTHETIC / HISTORY / UNKNOWN), statusem
  MT5 i panelem szczegółów, świeżością danych, instrumentem (tylko wyświetlenie), trybem, Execution Lock, powiadomieniami. Sekcje paneli
  są puste i oznaczone „etap N – nie zintegrowane”. Bez połączenia z backendem stan MT5 = UNKNOWN (ostatni znany tylko jako opis).
  Jeden store i jedno połączenie WS ze starym UI; stare trasy bez zmian; jedyna zmiana starego UI – pozycja „Nowe panele” w menu.
  **Backend, strategia, modele, ryzyko i wykonanie bez zmian.**
* **Etap 0 – uzupełnienie wg master promptu „COMPLETE”** (`docs/PEPE_UI_MASTER_PROMPT.md`): audyt §17 (zgodność, globalny wybór
  instrumentu bez nowych endpointów, status zlecenia po timeoucie, Performance & Journal, propozycja Random Forest N7, decyzja D9),
  mapa API §6, plan „Etap 1 – uzupełnienie”, testy F12–F16 i R11. Kod funkcjonalny bez zmian.

## 1.22.0 – Mapa stref PMW: High/Low Zone Engine + Daily Session Volume Intelligence + jedna mapa stref (ANALYTICAL_ONLY)
* **HLZE** (`zones/hlze.py`): strefy swingów M5/M15 (pivoty z `strategies/indicators`, istotność w ATR), pivoty prowizoryczne
  vs potwierdzone (`confirmed_at` = zamknięcie świecy pivot + right; nic nie jest datowane wstecz), granice knot–korpus z limitem
  szerokości (WIDE / odrzucenie), cykl życia ACTIVE → TESTED → WEAKENED / SWEPT / BROKEN / EXPIRED (przełamanie wyłącznie zamknięciem,
  sweep = knot + zamknięcie z powrotem, więcej testów = słabsza strefa), zmiana roli w BREAKOUT/BREAKDOWN_LEVEL, równe szczyty/dołki
  (płynność wyłącznie wnioskowana), poziomy poprzedniego dnia, poprzedniej sesji (`analytics/session_engine`), dnia bieżącego, konsolidacji.
* **DSVIE** (`zones/dsvie.py`): źródło wolumenu zawsze podane (TICK_VOLUME = aktywność brokera, nie wolumen globalny ani agresorów;
  order flow / footprint / arkusz = UNAVAILABLE), profile sesji z DST (POC, VAH/VAL 70%, HVN/LVN, ścieżka i migracja POC), stany
  DEVELOPING / COMPLETED / INVALID / STALE, wolumen względny tej samej sesji w tym samym czasie, kontekst sesji, strefy popytu/podaży
  tylko z dowodami (odrzucenie + przemieszczenie + kontekst; typ dowodu przy każdym).
* **UZICE** (`zones/uzice.py`, `zones/engine.py`): jedna mapa stref `PMW-ZONE-1.0` – łączenie tylko tej samej polaryzacji, zachowane
  pochodzenie, konflikty, punktacja 25/25/20/15/10/5 bez podwójnego liczenia, kary; wynik nie jest prawdopodobieństwem
  (`confidence_status` = UNVALIDATED).
* **ZoneService + API:** przeliczenie raz na zamkniętą M5, stabilne id, dziennik zdarzeń bez duplikatów, widok historyczny `as_of`;
  `GET /api/v1/zones/{map,status,events,profiles,context}`.
* **Ocena setupów (SHADOW):** `zone_context` każdego setupu; silna strefa przeciwna bliżej niż 1 R po kosztach → REDUCE w ocenie
  SHADOW (tylko przy danych OK); mapa późniejsza niż decyzja jest odrzucana. **Wykonanie bez zmian.**
* **ML:** schemat cech MQ-FEAT-1.1.0 = 1.0.0 + 26 cech stref z tego samego silnika; trener przyjmuje próbki 1.0.0 i 1.1.0; model 1.0.0
  ładuje się dalej (poprawka: wcześniej zmiana wersji schematu zablokowałaby czempiona). Bez automatycznego retreningu i promocji.
* **Wykres:** opcja „Strefy H/L + profil sesji” (Wykresy bota, Analiza AI) – strefy od chwili potwierdzenia, prowizoryczne przerywane
  z dopiskiem „PROW.”, POC/VAH/VAL, podpowiedź pod kursorem (typ, TF, status, wynik, testy, czas potwierdzenia, źródło wolumenu).
* Dokumenty: `docs/ZONE_ENGINE_ARCHITECTURE.md`, `docs/HIGH_LOW_ZONE_ENGINE.md`, `docs/DAILY_SESSION_VOLUME_ENGINE.md`,
  `docs/ZONE_AI_INTEGRATION.md`, `docs/ZONE_ENGINE_TEST_REPORT.md`. Walidacja predykcyjna na danych klienta – jeszcze niewykonana.

## 1.21.0 – Domknięcie planu po audycie: wspólny strażnik portfela, metryki, rozkład wyników, master models w pętli, O5, O8
* **Wspólny strażnik portfela (§23, Definition of Done 8):** nowe wejścia każdej ścieżki są sprawdzane względem dzisiejszego zrealizowanego
  wyniku i otwartych pozycji **obu** ścieżek (S01–S12 + SCALPING/HEDGING), wobec ostrzejszego z dwóch skonfigurowanych limitów
  (`PORTFOLIO_DAILY_LOSS_LIMIT`, `PORTFOLIO_MAX_OPEN_POSITIONS`). Błąd odczytu stanu portfela = brak nowych wejść. Zarządzanie pozycjami
  i transakcje ręczne bez zmian.
* **Metryki §22** w `/api/v1/stats` → `engines`: średni zysk i strata, maksymalny drawdown (pieniądze i R), błąd standardowy średniego R,
  rozbicie per strategia i per miesiąc.
* **Raport oceny setupów:** empiryczne częstości „TP przed SL / SL przed TP / żaden poziom w horyzoncie” z przedziałem Wilsona,
  mediana czasu utrzymania, log loss obok Briera.
* **Master models (AR-08):** inferencja na każdej zamkniętej świecy M5 we własnym wątku SHADOW (bez luk w ledgerze, także przy
  zamkniętym panelu); dryf kalibracji prognozy GPR liczony przez `mm/drift.py` (od 200 ocenionych prognoz).
* **O8:** promocja legacy ML wymaga zysku Briera ponad wskaźnik bazowy większego niż 2 błędy standardowe (jak `sh_tp_model`);
  modele ocenione przed 1.21 wymagają retreningu przed promocją. Działający czempion bez zmian.
* **O5:** sześć starszych raportów (ARCHITEKTURA, AUDIT, AUDIT_REPORT, AUDYT_MASTERQUO, AUDYT_WEJSCIOWY, RAPORT_1_3) przeniesione do
  `docs/archiwum/` z indeksem; treść bez zmian, odnośniki poprawione.

## 1.20.0 – Decyzje po audycie: ścieżka główna (O1), REDUCE na netting (O3), ocena SHADOW rozszerzona (O2, O4, O6)
* **Zmiana zachowania (O1):** na każdym instrumencie nowe wejścia otwiera tylko wybrana ścieżka główna – S01–S12 albo SCALPING/HEDGING
  (okno Tryb → „4. Ścieżka główna”, `POST /api/v1/mode/primary-path`, zapis w konfiguracji i w `settings_audit`). Druga ścieżka nadal
  analizuje setupy, ale ich nie wykonuje (`NOT_PRIMARY_PATH_*`). **Dopóki ścieżka nie jest wybrana, żadna nie otwiera nowych wejść**
  (`PRIMARY_PATH_NOT_SELECTED`, baner w panelu). Otwarte pozycje obu ścieżek są zarządzane; transakcje ręczne bez zmian.
* **O3:** HEDGING na rachunku NETTING działa bez pozycji przeciwnej – zdarzenie hedge kończy się częściowym zamknięciem (REDUCE).
  Dopuszczone dopiero po zaliczonej walidacji replay wariantu REDUCE na historii klienta (REAL_USER_DATA, n ≥ 30, wynik oczekiwany > 0);
  bez niej HEDGING na netting pozostaje zablokowany z podanym powodem. Profil: `hedge.netting_alternative` (REDUCE | BLOCK).
* **O2:** raport oceny pokazuje gotowość do ASSIST per silnik (cel 200 dojrzałych ocen z prawdopodobieństwem, Brier vs wskaźnik bazowy);
  ocena pozostaje SHADOW.
* **O4:** każda ocena zapisuje reżim obu definicji (MarketRegimeEngine i RegimeMachine v2); raport zestawia pary reżimów z wynikiem planu.
* **O6:** maszyna scalp Range→Sweep→Retest (SHADOW) jest trzecim źródłem ledgera ocen (zdarzenie TP1 przed SL; także kandydaci BLOCKED/MISSED).
* Test `test_ui_lab` (Swing Inspector): czekał na pojawienie się ramki, a nie na treść dociąganą osobnym zapytaniem – pod obciążeniem
  odczytywał „…”; czeka teraz na identyfikator swingu.

## 1.19.0 – Audyt architektury (Faza A) + wspólna ocena setupów (SHADOW)
* **Poprawka bezpieczeństwa (AR-01):** SCALPING/HEDGING respektuje STOP (kill switch), Execution Lock i powody wiązania rachunku z
  `ModeManager` – wcześniej czytał tylko nazwę trybu i po STOP otwierał nowe plany. Otwarte plany są nadal zarządzane. Test: `tests/test_arch_fixes.py`.
* Audyt architektury oparty na grafie importów i pomiarze wykonania (pętla bota 12 min + panel w Chromium): `ARCHITECTURE.md`,
  `COMPONENT_INVENTORY.md`, `INTEGRATION_MAP.md`, `REFACTOR_PLAN.md` (ustalenia AR-01…AR-16, decyzje O1–O8, stan Definition of Done).
* Nowy pakiet `backend/masterquo/evaluation` (SHADOW, bez dostępu do ścieżki zleceń – test statyczny):
  wspólny kontrakt `SetupCandidate`/`SetupAssessment` (lookahead = błąd kontraktu), ocena P nazwanego zdarzenia, EV netto, próg p* = L/(G+L)
  z kosztów i R:R, przedział Wilsona, jakość wykonania, konflikt portfela; ledger każdego setupu obu ścieżek (także zablokowanych) z
  dojrzewaniem wyniku z zamkniętych M1 (TP przed SL, MFE/MAE, wynik planu netto; świeca niejednoznaczna = SL).
* Widok łącznej ekspozycji obu ścieżek (tylko odczyt) i statystyki per silnik + łącznie (`/api/v1/stats` → nowe pole `engines`;
  pole `bot` bez zmian). API: `/api/v1/eval/status|assessments|report|exposure`.
* Test `test_nss` (kolejka NSS): warunek oczekiwania na odrzucenie starego zadania był spełniony przez wcześniejsze odrzucenia, co pod
  obciążeniem dawało wyścig z wątkiem roboczym; test czeka teraz na nowe odrzucenie.
* Zachowanie decyzji S01–S12 i SCALPING/HEDGING bez zmian poza AR-01. Zmiany zmieniające zachowanie bota czekają na decyzję użytkownika
  (`REFACTOR_PLAN.md` §4). LIVE zablokowany.

## 1.18.0 – Master models (XXX.rar): audyt, integracja, trening – SHADOW/OBSERVE
* Nowy pakiet `backend/masterquo/mm`: wspólne kontrakty wyjść (execution_allowed zawsze false), snapshot danych z sha256, splity chronologiczne
  z purge/embargo i jednorazowym holdoutem, niezmienne artefakty (promocja wyłącznie VALIDATED_SHADOW, rollback), ledger predykcji z dojrzewaniem etykiet, drift.
* Moduły: Align Mean, Kalman crossover, Breakout Zones + Robust Volatility, Tick Session Volume Profile, Multi-Indicator Strategy Pro, SMC BoS/IDM/FVG,
  HDC, GPR (Matérn 3/2), event engine (GRU + state stack, OpenCL), S3CE/STFS, STE-FlowNet, BUZOA (+ PSO/DE/Random), Math Fidelity Benchmark, tablica dowodów.
* Orchestrator 16 zadań (`python -m masterquo mm train`), zadanie `master_models` w runnerze treningu, API `/api/v1/mm/*`, ekran „12 Master Models”
  w panelu Neural Cyberpunk, narzędzie agenta `get_master_models` (prompt `MQAI-AGENT-PROMPT-2.1.0`, wiedza MM-K01..K06).
* Native MQL5 (`mql5/MasterModels`, `mql5/MathFidelity`): wskaźniki i EA bez handlu, self-test parytetu, 3 silniki benchmarku – nieskompilowane (brak MetaEditora).
* 6 pozycji bez specyfikacji w paczce (SDOm, Quant Momentum, Renko, H&S v2, Data Grabber, Chart Sync) – BLOCKED.
* Trening wykonany wyłącznie na danych syntetycznych: brak VALIDATED_SHADOW, `NO_VALIDATED_EDGE`. Raport: `docs/MASTER_MODELE_AUDYT_INTEGRACJA_PL.md`.

## 1.17.2 – Neural System: animowany, interaktywny mózg
* Okno Neural System (panel Neural Cyberpunk → Dashboard) powiększone do 640 px, z trybem pełnoekranowym (Esc zamyka).
* Animacja Canvas: sieć neuronów w kształcie mózgu (kontur, bruzdy kory, móżdżek, duże neurony z dendrytami), impulsy na połączeniach,
  paralaksa i „synapsy” do kursora; respektuje `prefers-reduced-motion`.
* Jasne neurony = moduły z rejestru `/api/v1/training/models` (kolor wg gotowości); najechanie pokazuje opis, kliknięcie przypina.
  Tło i impulsy są dekoracją – nie przedstawiają inferencji (opisane w legendzie).

## 1.16.0 – aktualizacje PMW-UPD 02–09, 11, 14 (kod; trening rynkowy i native nieuruchomione)
* Wdrożone sekwencyjnie według rejestru `docs/updates/update_registry.json`. Każda pozycja ma osobne statusy: kod / źródło / dane / trening / artefakty / native / edge.
  * 02 IQ/PAL/SAR (PARTIAL), 03 ML scalp, 04 Neural Scalp, 05 MTF dashboard, 06 heatmapa likwidacji + boxy sesji;
  * 07/08 Structure Intelligence + neutralizacja/SEW/kwotowania;
  * 09 SpikingBrain Finance / MiniRocket v2 (+ native MQL5) / reżim / SMMA / Z-Score;
  * 11 Markov + Heikin Flow + kanały S/R + StopDistance;
  * 14 VAMD + bounded Katz FD + Pullback/SMC (BoS/CHoCH/IDM/x) + Buffer Inspector.
* Nowe launchery 25–29; runner treningu ma 16 zadań; prompt agenta `MQAI-AGENT-PROMPT-2.0.0`.
* Wszystkie nowe modele działają w trybie SHADOW/OBSERVE, bez automatycznej promocji. Execution Lock bez zmian, brak zleceń.
* Bez REAL_USER_DATA i bez MetaEditora: trening rynkowy `NOT_RUN`, native `NOT_EXECUTED`, `NO_VALIDATED_EDGE`.
* **Naprawy treningu po zgłoszeniach (audyt `docs/AUDYT_PACZKI_1_16_PL.md`):**
  * czytelna przyczyna błędu eksportu;
  * akceptacja złota CFD zgłaszanego jako base=USD;
  * kontrola kompletności rozpakowania;
  * budżet RAM 8 GB ze skalowaniem próbki zamiast pomijania zadań;
  * automatyczna instalacja i walidacja `.venv_candles`.
* **`PepeMarketWizard.exe`** – launcher: instalacja, kalibracja + trening, kalibracja kontekstu, diagnostyka, start/stop bota, budżet RAM.
* Specyfikacje 01 (BB), 10, 12, 13 i 15 (EA) nie zostały dostarczone. Status BLOCKED, algorytmów nie rekonstruowano.

## 1.15.0 – instalatory treningu XAUUSD / BTC (`PepeMarketWizard_TRENING_XAUUSD_BTCUSDT.zip`)
* **Jeden wspólny mechanizm** `masterquo/training`, wywoływany przez cienkie launchery:
  * `00_TRENING_START.bat` (menu), `INSTALUJ_TRENING.bat`, `TRENUJ_XAUUSD.bat`, `TRENUJ_BTCUSDT.bat`, `TRENUJ_OBA.bat`, `DIAGNOSTYKA_TRENINGU.bat`;
  * `22_TRENUJ_WSZYSTKIE_MODELE.bat` (zgodność argumentów: prowizja dotyczy teraz tylko XAUUSD);
  * panel: Modele i trening → „Trening XAUUSD / BTC”.
* **Profile instrumentów** (`config/instruments_v1.json`): canonical_asset jest oddzielony od dokładnego symbolu brokera.
  * USD ≠ USDT; XAUT/PAXG/WBTC są odrzucane.
  * Domyślny symbol BTC to `BTCUSDT-`, z weryfikacją w terminalu, bez cichej zamiany.
* **Eksport per instrument** (M1–D1, porcjami, wznawialny, metadane, SHA256, jakość danych, prowizja z historii transakcji).
* **Cały łańcuch dla BTC:**
  * gold_candles (grid 500 jako hipoteza);
  * scalp A/B/C (profil BTC = reguły XAUUSD, wszystkie progi względne);
  * legacy ML (osobna baza `data/instruments/BTC/ml/ml.sqlite`, strumień setupów z symbolem BTC);
  * lab.
  * Osobne rejestry; XAUUSD zostaje w dotychczasowych katalogach.
* **Bot:**
  * ForecastService, ScalpService i ML przełączają model, profil i rejestr razem z aktywnym instrumentem;
  * SHADOW zapisuje kolumnę `instrument` (migracja 0015).
* **Lab:**
  * zapisywany jest **ten sam model, który oceniono** (fit na danych rozwojowych), bez refitu na train+holdout dziedziczącego status;
  * kontrola zgodności loadera i odrzucenia innego aktywa;
  * wskaźnik aktywnego modelu per rodzina i rollback.
* **Prognozy:**
  * zgodność loadera porównuje prawdopodobieństwa z pipeline'em treningowym na tych samych rekordach, nie tylko ich sumę;
  * model odrzucony nie zastępuje aktywnego (dotyczy też scalp).
* **APPROX tylko per zadanie:** `use_backfill_approx` nie jest już włączane w konfiguracji bota. Model z próbek APPROX ma status `RESEARCH_APPROX` i nie zostaje championem.
* **Statusy w trzech osiach** (wykonanie / jakość / integracja), udokumentowane kody wyjścia, wznawianie, anulowanie i blokada drugiego runu.
* **Raport HTML/JSON** z liczbami z bieżącego runu.
* **Dokumenty:** `MAPA_MODELI_I_TRENINGU.md/.json`, `START_TUTAJ_TRENING_PL.md`, `docs/schemas/*.schema.json`.
* **Bez zmian:** trening nie wysyła zleceń (eksport ma zablokowane funkcje zleceń), Execution Lock nienaruszony.

## 1.14.2 – jeden plik do treningu wszystkich modeli: `22_TRENUJ_WSZYSTKIE_MODELE.bat`
* Jedno uruchomienie (`python -m masterquo train-all`) wykonuje po kolei:
  1. start bota w tle, jeśli nie działa, i oczekiwanie na MT5;
  2. prognozy gold_candles: eksport M5/M30, trening z planem, przeładowanie w bocie;
  3. scalp ML/NN A/B/C: eksport M1–H1, trening (prowizja 0,50/lot/stronę lub z parametru), replay wariantów;
  4. ML Decision Tree / XGBoost: próbki z historii (APPROX – jawnie włączone; `--ml-no-approx` wyłącza) i trening;
  5. modele lab dla XAUUSD i BTC: wszystkie rodziny (LOGREG, drzewo, MiniRocket, XGBoost, ResNet1D, SEW-SNN, eksperymenty PCA/GMM/neutralizacja).
* Kroki zablokowane (np. za mało danych) są raportowane i nie zatrzymują kolejnych.
* Raport: `data/logs/trening_wszystkiego_<czas>.json`.
* Bot uruchamia teraz **wszystkie** zapisane modele lab danego aktywa na każdej zamkniętej świecy M5:
  * Pulpit → „Wszystkie modele” (wynik, czas, rola);
  * wybór modelu do wizualizacji; sieć neuronowa jest domyślnie pokazywana jako główna.
* Bez zmian: żadnego zlecenia, Execution Lock nienaruszony, modele bez zaliczonej walidacji działają w trybie badawczym (bez wpływu na decyzje).

## 1.14.1 – bez blokad symboli: bot pracuje na symbolach włączonych na rachunku
* Twoja zgłoszona usterka: na Twoim MT5 pojawiało się „SYMBOL_NOT_ALLOWED:DATA:XAUUSD-”, a dane z terminala przestały płynąć.
  Przyczyna: w 1.14.0 metadane kontraktu `XAUUSD-` u brokera nie przeszły reguły XAU/USD, a to blokowało cały symbol.
* Zmiana na Twoją prośbę:
  * **żadnych blokad po symbolu** – dane, analiza, skaner rynków (Market Watch jak przed 1.14), API i powiadomienia działają na włączonych symbolach;
  * metadane są tylko informacją;
  * gdy zapisanego symbolu nie ma u brokera, bot sam bierze pasujący symbol z rachunku (najpierw z Market Watch, z pominięciem XAUT, PAXG i WBTC);
  * BTC jest wykrywany automatycznie (status `AUTO_DETECTED`), bez potwierdzania;
  * symbol wpisany w Ustawieniach (MT5) znów działa i staje się symbolem aktywnego aktywa.
* **Bez zmian:** Execution Lock (blokada wysyłania zleceń) zostaje domyślnie włączony. Odblokowanie: Ustawienia → Execution Lock.

## 1.14.0 – dwa aktywa XAUUSD / BTC, Execution Lock, moduły badawcze M01–M42, protokół walidacji, panel 7 sekcji, aktywność sieci
* **Dwa aktywa:**
  * `assets/registry.py` – XAUUSD i BTC (allowlista) na wejściu danych (bridge), w API, treningu, skanerze, powiadomieniach i wykonaniu;
  * mapowanie symbolu brokera wyłącznie po metadanych (currency_base/profit, kontrakt), np. XAUT/PAXG ≠ XAU, WBTC ≠ BTC, BTCUSDT nie jest zakładany;
  * potwierdzenie przez użytkownika, fingerprint kontraktu (zmiana blokuje aktywo);
  * przełącznik w górnym pasku przełącza feed, cechy, modele, checklistę, wykresy i statystyki.
* **Execution Lock:**
  * proxy modułu MT5 w workerze odrzuca każde `order_send` (dowolna ścieżka, także bezpośrednie API i Trade Pad);
  * menedżer pozycji tylko odczytuje i rozlicza;
  * bramka i tryby pokazują `EXECUTION_LOCKED`;
  * odblokowanie tylko frazą w Ustawieniach; migracja ustawia LOCKED.
* **Moduły lab** (`lab/`, wszystkie na zamkniętych świecach, z `origin_time`/`confirmed_at`):
  * Markov, mapa reżimów, reżim zmienności, struktura swingów, trendlinie, płynność, sesje (zoneinfo/DST), ICT sweep→MSS→FVG→retest;
  * strefy S/D z trwałym zapisem (transakcja + snapshot + .bak), Memory Sequence;
  * SMMA(3) H/L, hipotezy Z-score, PSAR (wspólna implementacja), Stochastic Daily Breakout, quiet drift;
  * ACD i kinematyka z ticków (`copy_ticks_from`), ekstrapolator Fouriera z archiwum prognoz;
  * Repaint Inspector, drift CUSUM, bootstrap blokowy, Trade Pad (tylko symulacja).
* **Modele** (numpy, bez torch):
  * MiniRocket (clean-room), ResNet1D/ResNeXt (sprawdzenie gradientu), SEW-SNN z LIF, gradientem zastępczym, karą energetyczną i routingiem wg reżimu;
  * LOGREG/TREE/XGB, eksperymenty PCA/GMM/neutralizacja.
* **Protokół walidacji MQ-LAB-VAL-1.0.0:**
  * holdout z hashem i jednorazowym dostępem, walk-forward z purgingiem i embargo;
  * rejestr wszystkich prób, kontrole negatywne, kryteria promocji ustalone wcześniej;
  * werdykty INSUFFICIENT_EVIDENCE / NO_VALIDATED_EDGE;
  * artefakty z manifestem, blokadą aktywa i schematu oraz sumą kontrolną.
* **Scenariusze lab** (dla obu aktywów, tryb cienia): setup_id, checklista, trigger, unieważnienie; kompletność checklisty, wynik modelu i prawdopodobieństwo są rozdzielone.
* **Panel – 7 sekcji:**
  * Pulpit, Wykresy, Setupy, Modele i trening, Badania i walidacja, Dane i diagnostyka, Ustawienia; dotychczasowe strony jako podstrony;
  * Neural Network Activity z telemetrii tej samej inferencji: architektura, aktywacje, raster spike'ów; brak modelu → „Sieć nieaktywna”;
  * odpowiedzi dla nieaktywnego aktywa są odrzucane.
* **Naprawy wykryte przy przełączaniu aktywów:**
  * cache analityki 1.13 bez symbolu;
  * bufory bridge poprzedniego symbolu;
  * S01–S12, scalp i gold_candles dla BTC – jawnie niedostępne.
* **Migracje:** konfiguracja v11 (kopia `config.v10.bak.json`), baza 0014 (`lab_zones`, `lab_forecasts`, `lab_repaint`, `lab_trials`, `lab_holdout_access`, `lab_snapshots`).
* **Dokumenty:** AUDIT, RESEARCH_SOURCES, REQUIREMENTS_TRACEABILITY, ARCHITECTURE, VALIDATION_PROTOCOL, VALIDATION_RESULTS, MODEL_CARDS/, DATA_REQUIREMENTS, RUNBOOK_PL.
* **Ograniczenia:**
  * żaden model ani scenariusz nie jest zwalidowany rynkowo (brak historii MT5 w środowisku budowania);
  * źródła MQL5 i prace naukowe były niedostępne z sieci – implementacje własne.

## 1.13.0 – PepeMarketWizard: panel w grupach, wspólny silnik BB/MA, FFT/EMD/VMD, Double Bottom z biblioteką, audyt
* **Nowa nazwa: PepeMarketWizard** (monitor, tytuły, komunikaty, paczka `PepeMarketWizard_KLIENT_1_13_0.zip`). Pakiet `masterquo`, folder `data\`,
  klucze przeglądarki i nazwy plików `.bat` bez zmian (zgodność z istniejącą konfiguracją i skrótami).
* **Panel:** menu w grupach Rynek / Analiza / Praca bota; nowe strony Pulpit, Kontekst rynku, Indykatory, Analiza sygnału, Formacje i biblioteka,
  Pozycje i ryzyko, Dziennik i wyniki, Testy i raporty, Diagnostyka (istniejące moduły zachowane i wpięte); domyślny motyw złoty (#0F1214 / #D8B45F,
  świece biało-szare) dla nowych instalacji; „DANE PRZYKŁADOWE” w trybie demo; Pulpit startowy.
* **Wspólny silnik BB/MA** `analytics/ta.py` (MQ-TA-1.0.0): BB z odchyleniem populacyjnym, %b bez przycinania, bandwidth ratio/%, squeeze względem
  przeszłości, zdarzenia pasma; SMA/EMA/WMA, przecięcia potwierdzone zamknięciem ze stałym ID, kontekst wg jawnych reguł. Linie EMA/BB na wykresach
  liczone tym samym silnikiem (zgodność z M02I i modułem scalp potwierdzona testem).
* **FFT / EMD / VMD** `analytics/signal.py`: numpy/scipy bez nowych zależności, okno ciągłe (luki → unavailable), metadane wejścia, flagi jakości,
  pomiar rewizji końca okna, limit czasu, wątek roboczy z kolejką i cache, odrzucanie spóźnionych wyników.
* **Double Bottom** `analytics/double_bottom.py` + `library.py`: walidator INVALID/CANDIDATE/CONFIRMED/FAILED (pierwsze rozstrzygnięcie ostateczne),
  biblioteka próbek (zapis z zakresu świec, import/eksport), VALIDATE SELECTED/ALL (job_id, postęp, anulowanie, raport JSON/CSV), SHOW ON CHART ze
  współrzędnymi walidatora, skaner przyczynowy z czasem dostępności i zdarzeniami.
* `AnalyticsService` (tryb OBSERVE), archiwum wyników z chwili decyzji (`analytics_snapshots`), karta „Co wspiera analizę” z wyjaśnieniem
  budowanym wyłącznie z danych strukturalnych. Migracja 0013 (tylko nowe tabele). API `/api/v1/analytics*`, `/api/v1/patterns/*`.
* **Audyt:** `AUDIT_REPORT.md`, `INTEGRATION_MAP.md`, `TEST_REPORT.md`; naprawione ciche wyjątki (start silnika, ładowanie challengerów ML),
  nieużywane importy; ujednolicona implementacja BB.

## 1.12.0 – scalp M5 Range → M1 Sweep/Reclaim → Retest + kontrolowany hedge + ML/NN (wszystko SHADOW)
* Jeden automat **MQ-SCALP-RANGE-SWEEP-1.0.0-RESEARCH** (`backend/masterquo/scalp/`, profil z jednostkami `config/scalp_profile_v1.json`):
  zamrożony zakres M5, sekcja M1 z `known_at`, sweep/reclaim z potwierdzeniem świecy i tick volume, retest ≤3 M1, limit pogoni (MISSED),
  SL/TP1(MID)/TP2, filtr koszt/TP1 i ważonego RR netto, wielkość pozycji w dół do kroku lota, BUY/SELL lustrzane, dziennik stanów.
* Wskaźniki BB SMA20 ±2σ (populacyjne) / %B / BandWidth / percentyl / nachylenie, Parabolic SAR 0.02/0.2, sesje z IANA DST,
  własny silnik świec **SCI-1.0.0** (jeden dowód na rodzinę, ZERO_RANGE, przyczynowe statystyki z shrinkage).
* Adaptery zewnętrzne ze statusami (IQ Gold Gann / FX Gann / Star Lines / Volatility Master / heatmapa: UNAVAILABLE; **PAL02M:
  UNDOCUMENTED_EXTERNAL**) – bez fikcyjnych wartości; opcjonalny mostek plikowy dla licencjonowanego eksportu (UNVALIDATED).
* Kontroler hedge (SHADOW): NETTING → REDUCE, 1 hedge ≤50% base, TTL 3 M1, osierocona noga, timeout → rekonsyliacja, P&L koszyka.
* Replay z Bid/Ask, prowizją, poślizgiem, częściowym TP, konserwatywną kolejnością OHLC; porównanie HOLD/REDUCE/CLOSE/HEDGE_PARTIAL na tej samej ścieżce.
* Serwis SHADOW w bocie: bramki AND (brak informacji = BLOCKED), zapis decyzji przed wynikiem (`scalp_shadow`, migracja 0012), rozliczenie
  hipotetyczne, statusy CODE/DATA/MODEL/STRATEGY/HEDGE_VALID i EXECUTION_AUTHORIZED=false. API `/api/v1/scalp`, `/api/v1/scalp/shadow`.
  Konfiguracja `scalp`: `mode=SHADOW`, `live_trading/ml_execution/hedge_execution` tylko `false`.
* ML/NN w `.venv_candles`: kontrakt cech SCALP-FEAT-1.0.0, zadania A (1/3/5 min, martwa strefa kosztów), B (P(TP1 przed SL) z replayu),
  C (polityki hedge); LR, HistGradientBoosting, **MLP 64/32** z early stopping na późniejszym fragmencie, kwantyle; plan przed treningiem,
  walk-forward, kalibracja, holdout raz, rejestr z checksumami, inference w workerze (`scalp_forecast`).
* Eksport M1/M5/M15/M30/H1 (`export-scalp`), replay CLI (`scalp-replay`), launchery 16–21. Monitor: Wykresy bota → sekcja Scalp (6 widoków).
* **Warianty poprawy win ratio (profil 1.1.0)**: filtry jakości (tick volume, głębokość sweepu, rodziny świec), filtr sesji (godziny UTC,
  po otwarciu Londynu/NY), tryb trendu BOTH/ANY/ANY_PLUS_H1 (H1 dodane do kontekstu), jakość zakresu, close retestu przy krawędzi, wejście
  LIMIT_EDGE, BE + koszty po TP1, wyjście bez postępu, filtr modelu B (P(TP1 przed SL), cechy setupu, LR/HGB/MLP, kalibracja, próg z development).
  Domyślnie zachowanie 1.0.0; `scalp-replay --variants` (i `19_REPLAY_SCALP.bat`) porównuje 15 wariantów: win ratio i expectancy obok siebie,
  wybór po expectancy w development, test raz, stres kosztów +50%. Monitor: tabela wariantów, filtr B, win ratio. Wynik hipotetyczny SHADOW
  w monitorze liczony teraz po prowizji i poślizgu.
* Domyślna prowizja w paczce: **0.50 za 1 lot na stronę** (`scalp.commission_per_lot_side`; launchery 17/19 działają dwuklikiem, argument nadpisuje).
* **Trening i replay na danych rynkowych NIE wykonane – BLOCKED_NO_REAL_DATA.** Hedge vs REDUCE nieoceniony. Nic nie jest dopuszczone do wykonania.
  Raport: `research/scalp/RAPORT_SCALP_HEDGE_ML_NN.md`, opis: `docs/SCALP_HEDGE_ML_NN_PL.md`.

## 1.11.0 – świece i prognozy 5/15/30 min (gold_candles, SHADOW) + Double Retest v2 (badawczo)
* Moduł referencyjny `gold_candles` (MasterQUO_XAUUSD_CANDLES_FORECAST_v2) dołączony **bez zmian** (`backend/gold_candles/`, hashe zgodne z MANIFEST).
  Działa w izolowanym `.venv_candles` (numpy 2.3.5 / pandas 2.2.3 / scikit-learn 1.8.0) – środowisko bota bez zmian.
* Analityka SHADOW w bocie: zamknięte M5/M30 z sesji bota → proces roboczy (bez drugiej sesji MT5) → formacje, prognozy P(spadek/płasko/wzrost)
  i q10/q50/q90 dla 5/15/30 min; statusy NO_CANDLE_ENV / NO_MODEL / WARMUP / STALE_DATA / CONTRACT_MISMATCH / FORECAST_UNAVAILABLE.
  Prognozy zapisywane przed wynikiem (`forecast_shadow`, migracja 0011) i oceniane po upływie horyzontu. Zawsze `execution_permission=false`.
* Eksport historii `python -m masterquo export-candles` (11_EKSPORT_HISTORII_XAUUSD.bat): cutoff zamrożony, porcje z checkpointami, metadane
  ze specyfikacją brokera (tick_size), raport jakości danych. Trening `12_TRENING_MODELI_XAUUSD.bat`: zamrożony plan ze wspólnymi granicami
  UTC dla 5/15/30, purge/embargo, baseline i model bez formacji zadeklarowane przed treningiem, bootstrap bloków dni, statusy, rejestr z
  atomową aktywacją, walidacja (13) i rollback (14).
* Maszyna stanów **MasterQUO Gold Double Retest 5/10/15 v2** (BUY/SELL lustrzane, dwa epizody, reclaim, retest, rodziny REJECTION /
  CONTINUATION z tych samych flag formacji) – tylko badawczo, najwyżej RESEARCH_SETUP_COMPLETE, EXECUTION_STATE=BLOCKED.
* Monitor: Wykresy bota → „Świece i prognozy”. API: `/api/v1/forecast`, `/api/v1/forecast/shadow`, `/api/v1/forecast/reload`.
* **Trening na danych rynkowych nie został wykonany w środowisku budowy (BLOCKED_NO_REAL_DATA)** – wymaga eksportu z Twojego MT5.

## 1.10.1 – połączenie z MT5 po „-6 Terminal: Authorization failed”
* Program nadal łączy się domyślnie z **zalogowanym** terminalem. Nowe: opcjonalny **login i serwer** (Ustawienia → MT5) oraz **hasło** zapisywane
  wyłącznie lokalnie (`MT5_PASSWORD`, Windows DPAPI) – nie trafia do `config.json`, logów, odpowiedzi API ani przeglądarki (maska „•••”).
* Odrzucone logowanie **nie jest ponawiane w pętli** (ochrona przed blokadą rachunku u brokera) – kolejna próba dopiero po zmianie loginu, serwera
  lub hasła; w międzyczasie program próbuje sesji zalogowanej w terminalu.
* Gdy `terminal_path` jest pusty, a domyślny terminal zwraca -6 / błąd IPC, program próbuje **uruchomionych** terminali `terminal64.exe`
  (kilka instalacji MT5) i zapamiętuje ten, który zadziałał. Nie uruchamia innych instalacji. Ustawiona ścieżka nigdy nie jest zastępowana.
* Komunikat błędu z polską podpowiedzią (pasek awarii, Ustawienia → MT5, `02_DIAGNOSTYKA.bat`); przycisk „Połącz ponownie” w Ustawienia → MT5.
* Testy: `test_mt5_login.py` (7). Bez zmian strategii, ryzyka i wykonania.

## 1.10.0 – audyt winrate/ROI z naprawami P0, walls HV/IV + formacje + S12, panel na trzy strony
**Audyt 1.9.0** (`audit/`): reprodukcje A–J w izolacji (`audit/repro/repro_audit.py`) – na 1.9.0 8/8 ODTWORZONE, po naprawach 0/8.
Plan ulepszeń winrate/ROI, protokół walidacji i wyniki testów w `audit/`. Brak danych do oceny skuteczności: **OOS_NOT_RUN / NIE_OCENIONO_SKUTECZNOŚCI**.

**Naprawy P0 (wykonanie, etykiety ML, statystyki):**
* Jedna polityka wyjścia **MQ-EXIT-POLICY-1.0.0** (`execution/policy.py`) zapisywana przy otwarciu i używana przez LIVE, PAPER, etykiety ML i replay:
  wszystkie cele (także środkowy), wagi częściowych wyjść, BE dopiero po POTWIERDZONYM TP1, `time_exit_bars` z planu (jawny brak dla S11), TP od fillu (RR_FROM_FILL).
* Częściowe wyjścia jako maszyna stanów (REQUESTED / UNKNOWN / CONFIRMED / REJECTED / SKIPPED_VOLUME / NOT_FOUND_CHECK_TERMINAL); `trades.status`
  OPEN_PARTIAL / CLOSED / UNSETTLED – statystyki, winrate i R tylko z CLOSED; ROI rachunku pomija wpłaty/wypłaty (typy 2–6).
* Etykiety ML **MQ-LABEL-1.1.0**: kursor po TP1, kolejność wewnątrz świecy z kwotowań, bez nich AMBIGUOUS; koszty **MQ-COST-1.1.0** z tego samego źródła
  prowizji co wykonanie; COST_UNKNOWN wyłączone z treningu; champion oceniany na tych samych próbkach testowych; purge względem każdego późniejszego bloku.
* Migracja bazy **0009** (polityka wyjścia, stan TP1, status transakcji). Pozycje otwarte w 1.9 dostają politykę odtworzoną raz z zapisanych poziomów.

**Walls, formacje, S12:**
* Dostawca walls **MQ-WALLS-1.0.0**: HV_PROXY (zmienność historyczna brokera – przybliżenie, nie IV), IV_MANUAL, import IV (`import-iv`, `POST /api/v1/walls/iv-import`);
  snapshot sesji zamrażany i wersjonowany (migracja **0010**). Etykiety zawsze ze źródłem („HV-proxy”, nigdy „IV” dla HV).
* Silniki formacji: wykresowe **MQ-CHART-1.0.0** (pivoty z `known_at`, stany FORMING / CONFIRMED / INVALIDATED / EXPIRED), świecowe **MQ-CANDLE-1.0.0**
  (zdarzenia dowodowe), strefy S/R **MQ-SR-1.0.0** (W1/MN1 z D1), zakres M5 + strefy M1 **MQ-RANGE-1.0.0**. Definicje: `docs/PATTERN_DEFINITIONS_PL.md`.
* Nowa rodzina **S12 WALLS_RANGE_FAMILY** (RANGE_RECLAIM / WALL_REJECTION / BREAKOUT_RETEST + arbiter) – CANDIDATE, **tylko skanowanie** (jak S11).
  Opis: `docs/STRATEGIA_WALLS_RANGE_PATTERNS_PL.md`; ujednolicenie S01–S12: `docs/MAPA_UJEDNOLICENIA_STRATEGII_PL.md`.
* `data\config.json` v9 → v10: sekcja `walls`, przełącznik S12 `{scan: true, trade: false}`; listy strategii z rejestru.
* API: `GET /api/v1/timeframes`, `GET /api/v1/walls`, `POST /api/v1/walls/iv-import`, `GET /api/v1/structure?tf=`; agent: narzędzie `get_walls_and_patterns`.

**Panel na trzy strony** (`docs/POSTEP_PRZEBUDOWY_PANELU_CLAUDE_CODE.md` – mapa przeniesionych paneli):
* **Analiza AI** (`#/ai`): karta „Sygnał AI” (KUPNO / SPRZEDAŻ / CZEKAJ / BEZ TRANSAKCJI, kierunek, etap, strategia, czas i ważność, strefa, unieważnienie, cele)
  oddzielona od **pozwolenia silnika**; stany: aktualna / wygasła / inny setup / brak klucza / błąd ostatniego przebiegu (historia wyraźnie oznaczona);
  pełne wyjaśnienie (za, przeciw i sprzeczności, aktywacja, unieważnienie, 3 scenariusze, braki danych, dowody); „Analizuj teraz” / „Zapytaj AI” bez
  podwójnych wysyłek; wykresy H1 → M30 → M15 → M5 → M1 z wykresem głównym (domyślnie M5) i przełącznikiem „Siatka 5 wykresów”.
* **Wykresy bota** (`#/wykresy`): wszystkie TF z rejestru backendu (D1…M1) z rolą, stanem danych i wyróżnieniem wymaganych; widoki Wszystkie / Kontekst /
  Setup i wejście / Skupienie; 1–3 kolumny; sekcje: zmienność i walls, reżim, monitor strategii, inne rynki, jakość danych.
* **Warunki setupu** (`#/warunki/<setup_id>`): lista z filtrami i „Wybrany przez bota”, podsumowanie „Spełniono X z Y warunków wymaganych”, checklista w 10 sekcjach
  (Spełnione / Niespełnione / Oczekiwanie / Brak danych / Nie dotyczy, TF i czas), karta triggera i unieważnienia, plan wejścia, „Pokaż na wykresie”.
  **Oglądanie setupu nie zmienia strategii silnika**; zmiana to osobne ustawienie „Działanie bota – wybór strategii silnika”.
* Wspólna rama: kompaktowy pasek (symbol, MT5, dane, tryb, STOP), rozwijane „Konto”, panel „Pozycje i statystyki”, „Logi”, pasek awarii na każdej stronie;
  routing hash (Wstecz/Dalej, link, odświeżenie), pamięć ostatniej strony i układów; jedno połączenie WebSocket; widoki i kolory wykresów z 1.9 migrowane.

## 1.9.0 – wersja bez licencji
* **Licencjonowanie usunięte w całości** (na prośbę użytkownika): serwer licencji i panel administratora (`server/`), moduł klienta
  `backend/masterquo/license`, pytanie o klucz `MQL72-…` w `masterquo_start`, blokady silnika / skanera / sygnałów / ML / agenta / zleceń /
  API / WebSocket, plansza „Licencja nieaktywna” i wskaźnik licencji w monitorze, `09_KONFIGURACJA_LICENCJI.bat`, zmienne
  `MASTERQUO_LICENSE_*`, pakiety `cryptography`/`pyjwt`. Paczka serwera licencji nie jest już budowana.
* Start: `masterquo_start.bat` / `03_START_MASTERQUO.bat` – monitor od razu, bez klucza.
* `data\config.json` v8 → v9: sekcja `license` usuwana, pozostałe ustawienia bez zmian. Baza bez nowych migracji.
* Bez zmian: sygnały, M30/H8, S11, karta BUY/SELL, wybór setupu, szczegóły, dźwignia / limit ekspozycji, ROI rachunku, tryby wykonania.

## 1.8.0 – wybór setupu, szczegóły scenariusza, dźwignia / limit ekspozycji
* **Setup: AUTO / WYBRANY SETUP / WSZYSTKIE** (pasek nad kartą sygnału). AUTO = dotychczasowy wybór silnika; WYBRANY SETUP = silnik
  analizuje i wybiera tylko wskazaną strategię z rejestru (nic nie jest wymuszane – setup musi zostać wykryty i przejść wszystkie bramki);
  WSZYSTKIE = lista scenariuszy (stabilny identyfikator, symbol, kierunek, TF, czas powstania) z przyciskiem „Szczegóły”. Wybór zapisuje się
  w bazie **per rachunek MT5 (serwer:login)** i wraca po odświeżeniu i restarcie; odświeżanie go nie zmienia.
* **Szczegóły setupu**: strategia, symbol, kierunek scenariusza (oddzielony od zgody na wejście), interwały, status scenariusza
  (OCZEKIWANIE / WARUNKI SPEŁNIONE / UNIEWAŻNIONY / BRAK DANYCH), możliwość wejścia (DOSTĘPNE / ZABLOKOWANE + przyczyny), kontekst i uzasadnienie,
  checklista (warunek, próg, wartość, status, powód; warunki świecowe dopiero po zamknięciu), strefa wejścia, trigger, SL, TP, unieważnienie,
  R brutto/netto, wolumen, szacowana strata przy SL, wynik przy TP, margin i wolny margin po wejściu, wiek i aktualizacja, źródło danych,
  zgodność/konflikt interwałów strategii (w tym M30/H8), wynik ACTIVE z opisem (nie prawdopodobieństwo), historia tylko z rozliczonych transakcji.
* **Dźwignia / limit ekspozycji** (Ustawienia → Ryzyko): AUTO (dźwignia rachunku z MT5) albo RĘCZNIE (1:1…1:500, nie więcej niż dźwignia
  rachunku). Pokazywane osobno: dźwignia rachunku, limit użytkownika, efektywna ekspozycja (nominał / equity). To limit planowania bota –
  nie zmienia dźwigni u brokera; margin zawsze z `order_calc_margin`.
* **Wielkość pozycji** = największy wolumen spełniający jednocześnie: budżet ryzyka do SL, wolny margin z buforem i rezerwą zleceń
  oczekujących, limit ekspozycji (pozycje + zlecenia oczekujące), maks./min./krok wolumenu; zaokrąglenie w dół i ponowna weryfikacja
  kalkulatorami brokera. Nominał z `order_calc_profit` (bez założonej wielkości kontraktu). Minimalny lot ponad limit → blokada z powodem.
  Wyższa dźwignia nie zwiększa budżetu ryzyka i nie przesuwa SL/TP. Zlecenia oczekujące liczą się do ryzyka, marginu, ekspozycji i liczby pozycji.
* **Spójność**: wersja ustawień w każdej kalkulacji; przed wysłaniem zlecenia bramka sprawdza wersję ustawień i przelicza ryzyko na bieżącej
  cenie i danych rachunku (`order_check` jak dotąd) – zmiana ustawień lub mniejszy dopuszczalny wolumen blokuje wysyłkę. Istniejące pozycje
  i zlecenia nie są modyfikowane. Tryby wykonania bez zmian.
* **ROI rachunku MT5** (statystyki): metodą Dietza z zapisanych snapshotów equity, wpłaty/wypłaty jako przepływy – brak danych = „brak danych”.
* Migracja bazy 0008 (`account_prefs`).

## 1.7.1 – czytelny monitor: BUY / SELL, karta sygnału, prosta checklista
* **Karta sygnału na górze monitora**: duże BUY (zielone) / SELL (czerwone) tylko dla aktualnego, potwierdzonego sygnału otwarcia,
  który przeszedł reguły strategii i decyzji; OCZEKIWANIE (bursztynowe) z „Plan: BUY/SELL”; BRAK SYGNAŁU, BLOKADA (z powodem),
  NIEAKTUALNY, BRAK DANYCH. Każdy stan ma napis (nie tylko kolor). Wejście / SL / TP / RR dużą czcionką z podpowiedziami skrótów,
  ryzyko i wolumen, czas wygenerowania i ważności z odliczaniem, aktualność danych, jedno zdanie „dlaczego”, trigger, unieważnienie,
  źródło (STRATEGIA / STRATEGIA + AI), widoczne „AI NIEDOSTĘPNE”, rozdzielone: cena odniesienia / planowane wejście / wykonanie.
  „Kopiuj plan” kopiuje dokładnie wartości z karty. Długie uzasadnienia, identyfikatory i diagnostyka – w „Szczegóły”.
* **Prosta checklista** obok karty: spełnione ✓ / niespełnione ✗ / brak danych ?, z opisem i podsumowaniem „Do potwierdzenia brakuje: …”;
  tylko warunki wybranej strategii i bramek decyzji (tryb wykonania nie jest warunkiem potwierdzenia – osobna informacja na karcie).
* **Kontekst interwałów** (M1…D1, w tym M30 i H8): kierunek, rola, ostatnia zamknięta świeca, tworząca się świeca, dostępność danych,
  konflikt z planowanym kierunkiem i jego realny wpływ na kwalifikację.
* **Spójność**: backend buduje jeden model prezentacji (`engine/signal_view.py`, `MQ-SIGNAL-VIEW-1.0.0`) z tej samej decyzji
  (snapshot / decyzja / sygnał); zmiana stanu karty (TTL, blokada, ocena AI) jest wysyłana od razu. Monitor tylko obniża stan:
  po upływie ważności → NIEAKTUALNY, bez połączenia lub przy decyzji starszej niż 2 min → BRAK DANYCH; po ponownym połączeniu karta
  pochodzi z bieżącej decyzji silnika (stara karta nie wraca jako BUY/SELL). Spóźniona odpowiedź AI nie zmienia stanu ani źródła.
* Historia sygnałów: BUY/SELL zamiast LONG/SHORT, przycisk „Kopiuj” w każdym wierszu.
* Bez zmian: logika strategii, progi wejścia, risk engine, tryby wykonania, M30/H8, licencje.

## 1.7.0 – sygnały z planem wejścia, M30/H8, strategia EMA20 Pullback, licencje 72 h, panel administratora
* **Sygnał (kontrakt `MQ-SIGNAL-1.0.0`)**: status (OCZEKIWANIE/POTWIERDZONY/ZABLOKOWANY/UNIEWAŻNIONY/WYGASŁY/BRAK_DANYCH) i osobny stan
  wykonania, ceny (odniesienie, Bid/Ask, planowane wejście, fill dopiero po wykonaniu), SL/TP, ryzyko w pieniądzu i %, wolumen, RR brutto
  i netto z definicjami, spread vs SL, koszty, flagi danych, warunki spełnione/brakujące, wyzwalacz, unieważnienie, powody blokad,
  ocena AI (aktualna / nieaktualna / niedostępna), jakość, prawdopodobieństwo tylko z walidowanego modelu. Blok „Sygnał AI / plan wejścia”
  obok checklisty, zakładka „Historia sygnałów” z filtrami (migracja 0007).
* **M30 i H8** w całym systemie: rejestr interwałów, natywne TIMEFRAME_M30/H8 z MT5, kontrolowany resampling H8 z H1, jakość danych
  (kontekst), karta „Kontekst M30/H8”, układ 8 wykresów, eksport (8 TF, model DST `NY_CLOSE`), narzędzia agenta.
* **Strategia S11 EMA20 Pullback 2.5R**: audyt Pine (14 punktów), poprawiony Pine v6 (nieskompilowany – brak TradingView), port oryginału
  i wersji naprawionej, backtester (model Pine i MT5, walk-forward, test końcowy, bootstrap), RAPORT_WYNIKOW.md (dane syntetyczne).
  Domyślnie tylko skanowanie (bez automatycznego handlu).
* **Statystyki**: winrate netto bez breakeven (BE osobno), PF „brak strat”, oczekiwana wartość w R, ROI Dietza (wpłaty nie są zyskiem),
  statystyki sygnałów oznaczone jako brutto w R.
* **Licencje 72 h**: osobny serwer `server/mqlicense` (SQLite, migracje, Ed25519, Argon2id, TOTP, CSRF, audyt, limity) i panel administratora
  `/admin/`. `masterquo_start.bat` prosi o licencję **przy każdym uruchomieniu**; bez ważnej dzierżawy silnik, skaner, sygnały, ML,
  agent, nowe zlecenia i API/WS monitora są zablokowane (otwarte pozycje i SL/TP bez zmian). Config v8 (sekcja `license`).
* Audyt: `AUDYT_MASTERQUO.md`. Instrukcja: `INSTRUKCJA_WINDOWS_PL.md`. Serwer: `server/README_SERWER_PL.md`.

## 1.6.0 – sygnały bota zamiast sygnałów agenta AI
* Sygnały tworzy **bot**: potwierdzone (CONFIRMED) setupy strategii S01–S10. Na symbolu głównym pochodzą z silnika bota, na pozostałych
  rynkach skaner uruchamia te same strategie (te same progi, parametry i przełączniki). Generowanie sygnałów przez Claude usunięte.
* Walidacja regułami bota: R:R ważony wagami celów ≥ `risk.rr_block_below`, cena nie dalej od wyzwalacza niż `max_distance_atr` strategii,
  SL/TP po właściwej stronie, spread ≤ 50% ryzyka; jeden sygnał na setup i na zdarzenie rynkowe; rozliczanie na M15; statystyki; Telegram.
* Monitor: panel „Sygnały bota · S01–S10”, kolumna „Setup bota” w skanerze, setupy i poziomy sygnałów w oknie rynku.
* Migracja bazy 0006 (kolumny strategii w tabeli sygnałów), konfiguracja v6 (sekcja `signals`; `ai_signals` usunięta), skan co 120 s.
* Poprawki strategii dla rynków o małych cenach (FX): grupowanie poziomów i usuwanie duplikatów celów bez zaokrąglania do 0,01.

## 1.5.0 – skaner wszystkich rynków i sygnały AI
* **Skaner rynków** (`markets/`): symbole z terminala MT5 – Market Watch (domyślnie), własna lista albo wszystkie symbole.
  Dla każdego: trend H1/H4/D1, RSI, ADX, ATR, Donchian, reżim, poziomy dzienne i IV walls, spread vs ATR, obserwacje i ranking do przeglądu.
  Tylko odczyt; strategie i zlecenia bota pozostają na symbolu głównym.
* **Sygnały AI** (`agent/signals.py`): Claude proponuje BUY/SELL/NO_TRADE z wejściem, SL i TP dla dowolnego rynku; walidacja deterministyczna
  (strony SL/TP, ATR, R:R, odległość wejścia, spread), zapis w bazie (migracja 0005), rozliczanie na świecach M15 (WIN/LOSS/EXPIRED/TIMEOUT),
  statystyki. Bez wysyłania zleceń. Automatyczne sygnały dla N najlepszych rynków – opcjonalne, domyślnie wyłączone.
* Monitor: panele „Rynki · skaner” i „Sygnały AI · Claude”, okno rynku z wykresem (M15/H1/H4/D1, IV walls, poziomy sygnału AI),
  linie aktywnego sygnału AI na wykresach symbolu głównego, zakładka ustawień „Rynki / Sygnały AI”.
* Most MT5: odczyt listy symboli, kwotowań i świec dowolnego symbolu. Symulator: kilka syntetycznych rynków.
* Opis: `docs/RYNKI_I_SYGNALY_AI.md`.

## 1.3.1 – zmienność dzienna i IV walls
* **Cofnięte**: konta, serwer licencji, panel administratora i licencje 48 h z wersji 1.4 (na prośbę użytkownika). Plik konfiguracji
  zapisany przez 1.4 (config v4 z sekcjami `central`/`connector`) wczytuje się bez błędu – te sekcje są usuwane.
* **Nowe**: `engine/volzones.py` – Daily Open, High/Low dnia, PDH/PDL, zmienność historyczna (close-to-close / Parkinson, percentyl 1R),
  wycena 1-dniowych opcji Black-76 (straddle ATM, progi rentowności), IV walls ±kσ z premią, deltą, P(zamknięcia za) i P(dotknięcia).
  IV = HV (MT5 nie ma opcji na złoto) albo IV wpisana ręcznie. Opis: `docs/IV_WALLS_ZMIENNOSC_DZIENNA.md`.
* Monitor: strefy i linie na wszystkich wykresach (przełącznik „IV walls / Daily”), panel „Zmienność dzienna · IV walls”, zakładka
  ustawień „Zmienność / IV”, nowe kolory w motywie. API `GET /api/v1/volatility`, narzędzie agenta `get_volatility_levels`. Config v5.
* Poprawki: STOP działa przy otwartej karcie monitora; testy offline nie zależą od dnia tygodnia (symulator rynku otwarty w testach).

## 1.3.0 – kolory, niezależny zoom, Decision Tree + XGBoost, tryby bez READONLY
* **Tryby**: SIGNALS („Analiza warunków”) / PAPER / AUTO_DEMO / AUTO_LIVE – trwały wybór (config v3, migracja DB 0003), konto z terminala,
  niezgodność blokuje z powodem, brak potwierdzania pojedynczych transakcji w AUTO, STOP tylko dla nowych wejść. Trzy niezależne
  ustawienia: wybór strategii, tryb ML (OFF/SHADOW/ASSIST), tryb wykonania.
* **ML** (`backend/masterquo/ml/`): kolektor setupów, FeatureEngine as-of, etykietowanie netto (SL/TP/BE/czas, kwotowania, AMBIGUOUS),
  niezmienne snapshoty, trener DT + XGBoost w osobnym procesie, walidacja chronologiczna z purgingiem/embargo, kalibracja, rejestr
  champion/challenger z regułami promocji i rollbackiem, kontrakt predykcji, dryf, backfill z MT5 (APPROX), węzeł ML w drzewie decyzji,
  ranking AUTO w ASSIST, API `/api/v1/ml/*`. Opis: `docs/ML_DECISION_TREE_XGBOOST.md`.
* **Wykresy**: naprawiony wspólny zoom (przyczyna w `RAPORT_1_3.md`), stan widoku per wykres, przyciski +/−/Dopasuj/Najnowsza/auto-skala,
  grupy synchronizacji, osobny wspólny celownik.
* **Kolory**: pełna paleta tokenów, picker HSV/HEX/RGB/HSL/alfa, presety, własne motywy, import/eksport z walidacją, ostrzeżenia kontrastu,
  nadpisania per wykres, przyciemnienie/przezroczystość GIF.
* **Monitor**: checklista wejścia zamiast sygnałów BUY/SELL, panel ML, osobne chipy MT5/instrument/dane/backend/wykonanie/AUTO/ML.
* Zależności: scikit-learn 1.9.1, xgboost 3.4.1, scipy 1.18.1, joblib 1.6.0, threadpoolctl 3.7.0, narwhals 2.26.0, cloudpickle 3.1.2 (hashe).

## 1.2.0 – ACTIVE, 10 strategii, AUTO wybór strategii, animowany monitor
* **10 strategii S01–S10** (`backend/masterquo/strategies/`): TREND_PULLBACK, ADAPTIVE_TREND (KAMA/ER), CHANNEL_BREAKOUT (Donchian),
  VOLATILITY_COMPRESSION_BREAKOUT, SESSION_RANGE_BREAKOUT (strefy IANA/DST), BREAKOUT_RETEST, FAILED_BREAKOUT_RECLAIM, RANGE_EDGE_REVERSION,
  STATISTICAL_MEAN_REVERSION (z-score), EXHAUSTION_STRUCTURE_REVERSAL. Wspólny kontrakt, LONG/SHORT jedną regułą (odbicie cen),
  status FUNCTIONAL_ONLY_OOS_NOT_RUN. Karty: `docs/PLAYBOOK_10_STRATEGII.md`, źródła: `docs/ZRODLA_I_ADAPTACJE.md`.
* **Profil ACTIVE** (domyślny): etapy WATCH/EARLY/CONFIRMED, punktacja 0–100 (25/25/20/15/10/5), progi 40/55/70 + prawdziwy trigger,
  tworząca się świeca tylko dla WATCH/EARLY, skan co ≥ 2 s przy nowych danych. Profil ORIGINAL = M07/M10A jak w 1.1.
* **MarketRegimeEngine** (TREND/RANGE/COMPRESSION/EXPANSION/EXHAUSTION/TRANSITION/DATA_UNAVAILABLE/STALE) z konfliktami TF i horyzontami.
* **SetupTracker** (tabela `strategy_setups`, migracja 0002): wersje setupów, histereza etapów, natychmiastowe unieważnienie/wygaśnięcie,
  STALE bez tworzenia nowych setupów, rewalidacja po restarcie, karty playbooka (także odwołane setupy).
* **StrategyAutoSelector** (AUTO/MANUAL): ranking, grupowanie event_id, konflikt LONG/SHORT, histereza wyboru, dziennik zmian
  (`strategy_selection_log`). AUTO wybiera strategię, **nie** włącza zleceń; „Skanuj” i „Dopuść do handlu” per strategia.
* Drzewo decyzji: węzeł STRATEGY dla ACTIVE, blokada STRATEGY_TRADE_DISABLED; gateway oznacza ENTERED dla setupów ACTIVE.
* Claude: prompt MQAI-AGENT-PROMPT-1.2.0, narzędzie z rankingiem AUTO, pola `preferred_strategy_id` (walidowane w rejestrze, tylko sugestia)
  i `scenario_still_valid`; wywołania przy zmianie wyboru i EARLY/CONFIRMED wybranego setupu.
* API: `/api/v1/strategy/auto|mode|toggle|profile|selection-log`, `/api/v1/playbook`, `/api/v1/appearance/assets|upload`, `/media/masterquo/{slot}`.
* Monitor: panele „AUTO — wybór strategii”, „Setupy na bieżąco” z „Dlaczego nie ma setupu?”, „Strategie (10) i dziennik AUTO”;
  nagłówek z przełącznikiem AUTO/MANUAL i osobnym statusem „Wykonywanie zleceń”; **animowane tło** (pierwszy GIF – wgrywany, bo dotarł
  jako statyczny WebP) i **tańcząca żaba przy BALANCE** (drugi GIF, oryginał z przezroczystością); tryby FULL/LIGHT/OFF z prawdziwą
  podmianą na kadr, prefers-reduced-motion, Page Visibility; responsywność 1920/1366/wąskie okno.
* Narzędzia: `tools/replay_strategies.py` (replay/OOS, porównanie z ORIGINAL), `tools/make_strategy_cards.py`, `08_PROFIL_ORIGINAL.bat`,
  `python -m masterquo profile ACTIVE|ORIGINAL|show`.
* Poprawka: odbicie cen dla SHORT wokół bieżącej ceny (nie zera) – wskaźniki względne (szerokość BB/średnia) poprawne dla SHORT.

## 1.1.0 – łagodniejsze bramki
Struktura H1_LEAD, RR od 1,0 (1,0–1,5 z połową ryzyka), AI jako weto, brak kalendarza nie blokuje, poślizg 20 pkt, okno wejścia 3 świece;
migracja konfiguracji v1→v2. Szczegóły: MIGRACJA_I_ZMIANY.md.

## 1.0.0 – pierwsze wydanie
Lokalna aplikacja MT5 → MasterQUO → Claude → ryzyko → monitor; READ_ONLY/PAPER/DEMO/LIVE.
