# Kronos w PepeMarketWizard 1.31.0 – raport wdrożenia

Data: 2026-11-04. Środowisko pracy: kontener Linux (x86_64, 4 rdzenie, bez GPU), Python 3.13.16, Node 22, Chromium (Playwright).
Bez Windows, bez terminala MT5 (symulator bota = dane SYNTETYCZNE). Żadnych zleceń.

## 0. Najważniejsze ograniczenie tego wdrożenia

Polityka sieci tego środowiska chmurowego **blokuje `huggingface.co` i `download.pytorch.org`** (odpowiedź proxy 403). PyPI działa.
Skutki:

* **oficjalne wagi NeoQuasar nie zostały tu pobrane ani uruchomione;**
* nie sprawdziłem tutaj dostępności przypiętych rewizji `901c26c…` / `0e01173…` – zrobi to instalator na Twoim komputerze przed
  pobraniem;
* sum SHA-256 plików wag nie dało się zapisać w repozytorium z góry. Instalator pobiera je z metadanych źródła (LFS sha256 / git blob
  sha1) przy pobieraniu, porównuje i zapisuje w `kronos_manifest.json`.

Wszystko, co dotyczy prawdziwych wag, wykonasz u siebie – rozdział 5. Przepływ (PyTorch, kod modelu, proces, kolejka, kontrakt,
panel, walidacja) przetestowałem na prawdziwym PyTorch 2.14.1 z **losowymi wagami** w układzie oficjalnych plików. Ich architektura
ma dokładnie 24 741 376 parametrów, czyli tyle, ile podaje README autorów dla Kronos-small (24,7 M). Pomiary czasu dotyczą więc
modelu tej wielkości, ale **liczby z tych prognoz nie są prognozami rynku**. Losowe wagi istnieją tylko w testach: manifest ma
znacznik `fixture`, a bot odrzuca go poza testami.

## 1. Zmienione i nowe pliki

**Nowe**
* `backend/kronos_runtime/`:
  * `vendor/kronos/{kronos.py, module.py, __init__.py, LICENSE, UPSTREAM.md}` – kod Kronos (MIT), zmieniony tylko import;
  * `lock.py` – przypięte repozytoria i rewizje;
  * `manifest.py` – sumy SHA-256 plików i ich sprawdzanie;
  * `install.py` – pobieranie wag i kontrola zgodności ze źródłem;
  * `engine.py` – ładowanie, wybór urządzenia, prognoza, ścieżki niepewności, test własny;
  * `worker.py` – proces inferencji (JSON lines);
  * `tests_data/` – dane testu regresji autorów.
* `backend/masterquo/kronos/`:
  * `settings.py`, `calendar.py`, `quality.py`, `service.py`, `predictions.py`, `validation.py`.
* `backend/masterquo/db/migrations/0024_kronos.sql` – tabela `kronos_forecasts` (dopisana, nic nie zmienia).
* `frontend/src/components/KronosForecastPanel.tsx` – panel „Kronos AI Forecast”.
* `33_KRONOS_INSTALUJ.bat`, `tools/kronos_setup.py`, `requirements/requirements-kronos-win.txt` (28 pakietów, 36 sum SHA-256,
  Windows cp312/cp313).
* `INSTRUKCJA_KRONOS.md`, ten raport.
* Testy:
  * `tests/test_kronos_bot.py`, `tests/test_kronos_runtime.py`, `tests/test_ui_kronos.py`;
  * dublery testowe: `tests/kronos_testkit.py`, `tests/kronos_stub_worker.py`, `tests/kronos_fixture.py`.

**Zmienione**
* `backend/masterquo/runtime.py` – start i stop serwisu Kronos, podpięcie do SH.
* `backend/masterquo/sh/service.py` – kontekst Kronos w każdej ocenie SCALPING/HEDGING (`_kronos`).
* `backend/masterquo/sh/models.py` – Kronos w rejestrze modeli SH z sondą stanu.
* `backend/masterquo/modelhub/{adapters.py, aggregate.py, catalog.py}` – PMW-PRED-1, wykluczenie regresji ceny z łączenia
  prawdopodobieństw, katalog.
* `backend/masterquo/api/app.py` – `/api/v1/kronos/*`.
* Frontend: `frontend/src/{store.tsx, pages/BotChartsPage.tsx, components/ShPanels.tsx, styles.css}`, `frontend/dist`.
* `tools/make_manuals.py` – sekcja Kronos w instrukcji administratora.
* Wersja 1.31.0: `version.py`, `winres.json`, `rsrc_windows_amd64.syso`, `build_release.py`.
* `CHANGELOG.md`, `START_TUTAJ_PL.md`.

## 2. Jak Kronos wpięto w istniejącą architekturę

* **Analiza:** aktywna wersja 1.30.1. Ścieżki wskazane w poleceniu istnieją i działają:
  * `mt5/bridge.py` + `mt5/worker.py` – świece i kolejka wywołań terminala;
  * `modelhub/*` – PMW-PRED-1 i katalog;
  * `forecast/service.py` – wzorzec: osobne `.venv_candles` + proces;
  * `sh/` – SCALPING/HEDGING;
  * `engine/decision.py` – S01–S12;
  * `CandleForecastPanel.tsx`.

  Execution Lock jest wycofany od 1.24 (Twoja decyzja) – nie został przywrócony.
* **Wzorzec izolacji:** taki sam jak przy prognozach świec (`.venv_candles`):
  * osobne `.venv_kronos` i osobny proces `kronos_runtime.worker`;
  * bot (bez torch) rozmawia z nim liniami JSON; proces ładuje model i tokenizer **raz**, w trybie eval, bez gradientów.
  * zależności PyTorch nie dotykają środowiska bota.
* **Dane:** wyłącznie **istniejący** most MT5:
  * aktywny symbol z bufora mostu (bez dodatkowych wywołań terminala);
  * drugi instrument przez `bridge.symbol_bars` (kolejka MT5Worker), co najwyżej raz na świecę;
  * M30 natywnie;
  * tylko świece zamknięte; czas UTC z offsetu serwera mierzonego przez most.
  * Symbole z mapowania aktywów – BTC dopiero po potwierdzeniu w Ustawieniach.
* **Wyniki:**
  * PMW-PRED-1: REGRESSION, jednostka `price`, kalibracja NOT_APPLICABLE; READY tylko dla prognozy bieżącej zamkniętej świecy;
  * katalog modeli `/api/v1/models/catalog`, rejestr SH (`sh/models.REGISTRY`, rola OBSERVATION);
  * agregacja: regresja ceny nie jest łączona z prawdopodobieństwami innych modeli (powód w `excluded`).
* **Strategie:**
  * `sh/service.cycle` dokłada do każdej oceny `su["kronos"]` (kierunek, relacja do strony, zgodność/konflikt z innymi gotowymi
    modelami i ze strukturą tego samego TF, opis zależności i tego, czego model nie widzi) oraz pozycję w checkliście;
  * OBSERVE = bez zmian w decyzji;
  * REQUIRED (po walidacji + potwierdzeniu) może tylko zamienić READY na WAIT – przed koordynacją, ryzykiem i otwarciem planu, więc nigdy
    niczego nie dopuszcza ani nie omija.

## 3. Komendy i faktyczne wyniki testów (uruchomione tutaj)

| Komenda (folder `tests`) | Wynik |
|---|---|
| `python -m unittest test_kronos_bot` (główne środowisko bota, bez torch) | **16/16 OK** |
| `.venv_kronos/bin/python -m unittest test_kronos_runtime` (PyTorch 2.14.1 CPU) | **7 OK, 1 pominięty** (oficjalne wagi – brak dostępu do HF) |
| `python -m unittest test_ui_kronos` (serwer + Chromium) | **2/2 OK** |
| `python -m unittest test_launchers test_sh_api test_sh_service test_sh_core test_sh_scenario test_sh_fixes test_sh_risk_state test_sh_setup test_mm_integration test_trainhub test_app_process test_desktop_app test_release_tools test_execution_lock_withdrawn test_telegram test_evaluation test_kronos_bot test_kronos_runtime` | **209 OK** (10 pominiętych: 8 testów torch w środowisku bez torch, 2 opcjonalne backendy) |
| UI: `test_ui_monitor` 11/11, `test_nc_panel` 1/1, `test_ui_training_center` 1/1, `test_ui_interface_129` 4/4, `test_ui_kronos` 2/2, `test_ui_scalp` 3/3 | OK |
| UI: `test_ui_pages` | patrz niżej |
| `tools/migration_check.py --old-ref 30cb0cf` (1.30.1 → 1.31.0) | **11/11 PASS** (migracje 22 → 23; powrót do 1.30.1 z kopii; 1.30.1 działa też na danych po 1.31.0) |
| `tools/verify_release.py --all` | OK ×2 |

`test_ui_pages`:
1. Pierwszy przebieg wykrył **prawdziwy** błąd: długi status Kronosa powodował poziome przewijanie przy 390 px na `#/wykresy`
   (`test_ui_scalp` 390 px tak samo). Poprawione w CSS – pomiar po poprawce: szerokość strony 390 px.
2. Po poprawce dwa przebiegi miały jednorazowe błędy, za każdym razem inne:
   * `test_05` (brak `need-note` w czasie oczekiwania) / `test_06` – raz;
   * `test_08` przy 1366 px na `#/warunki/bot` – raz.

   Bezpośredni pomiar tej strony przy 1366 px nie wykazał przepełnienia.
3. Kolejne **3/3** przebiegi przeszły, tak samo jak 3/3 przebiegi na 1.30.1. Uznaję to za niestabilność czasową testu. Nie mogę wykluczyć,
   że nowy panel (4 zapytania API przy wejściu na stronę) zwiększa jej prawdopodobieństwo.

**Co sprawdzają testy** (dublery testowe są oznaczone, nie są prognozami):
* kalendarz sesji: 24/7, przerwa dzienna i weekend złota, za krótka historia, niepewny slot; M1 liczone na slotach 5-minutowych;
* jakość danych: świeca otwarta wyłączona, sprzeczne duplikaty, złe OHLC, brak wartości, luki (DEGRADED/BLOCK), weekend nie jest luką,
  dane nieaktualne, za mało świec, wolumen REAL / TICK / brak;
* ustawienia: wartości domyślne, odrzucanie złych wartości, uszkodzony plik oznacza obserwację;
* bramka strategii: OBSERVE nie zmienia nic; REQUIRED wstrzymuje przy braku / bocznie / przeciwnym kierunku; nigdy nie podnosi
  WAIT/NO_TRADE do READY; w kodzie Kronosa nie ma odwołań do zleceń, pozycji ani MetaTrader5;
* serwis z zastępczym procesem: brak środowiska / brak wag (zero odczytów z terminala), prognoza → kontrakt PMW-PRED-1 → zapis →
  rozliczenie z prawdziwych świec (MAE, MAE „ostatnia cena”), MT5 rozłączony (prognoza nieaktualna), dane nieaktualne, symbol
  niepotwierdzony (zero odczytów), limit czasu (proces zabity, potem działa), awaria procesu i odtworzenie, błąd CHECKSUM →
  INCOMPATIBLE + odstęp, deduplikacja i limit kolejki, M30 natywnie;
* REQUIRED: bez potwierdzenia / bez raportu / z raportem syntetycznym – odmowa; z pozytywnym raportem DEMO – zgoda; powrót do OBSERVE;
* walk-forward: DEV przed TEST, horyzonty bez nakładania, dane syntetyczne nigdy pozytywne, test dwumianowy;
* PyTorch:
  * kod we własnej przestrzeni nazw (brak modułu `model`), licencja MIT obecna;
  * wykrywanie zmienionego pliku (CHECKSUM), odrzucenie manifestu testowego poza testami;
  * ładowanie i prognoza przy **zablokowanych gniazdach sieciowych** (offline);
  * eval / bez gradientów, CUDA żądane bez GPU → CPU z przyczyną, ładowanie raz na proces;
  * powtarzalność przy tym samym ziarnie; wynik **identyczny** z bezpośrednim wywołaniem oryginalnego `KronosPredictor.predict`;
  * bez wolumenu; 4 niezależne ścieżki z kwantylami q10 ≤ q50 ≤ q90; błędy wejścia (CONFIG);
  * niezgodna para (INCOMPATIBLE), brak wag (NO_WEIGHTS);
  * protokół procesu (zły JSON, nieznane polecenie, predict przed load);
  * instalator z podstawionym API Hugging Face: sukces + manifest, zła suma, zła rewizja, brak safetensors, tryb offline – przy
    błędzie nic nie zostaje oznaczone jako zainstalowane.

**Pomiary wydajności (CPU tego kontenera, 2 wątki, model wielkości Kronos-small z losowymi wagami):**
* ładowanie 0,39–0,55 s;
* prognoza 12 świec z kontekstu 400: **1,42–1,57 s**; 8 świec: 0,87 s;
* 8 dodatkowych ścieżek niepewności: +11,1 s;
* w bocie na symulatorze: ok. 1,9–2,6 s na prognozę (4 cele M5/M15 × XAUUSD/BTC liczone po kolei);
* walidacja 40 punktów startu przez API: 70 s.

**Instalator na żywo w tym środowisku:**
* krok pakietów (PyPI) zakończony powodzeniem;
* krok wag zakończył się czytelnym błędem: „brak połączenia z huggingface.co (internet, zapora albo proxy) – odblokuj huggingface.co
  i powtórz” (kod NETWORK). To zgodne z faktyczną blokadą.

**Obieg na symulatorze (serwer bota + PyTorch + losowe wagi):**
* przez pierwsze ~30 s cele są BLOCK „brak czasu UTC” – most mierzy offset serwera;
* potem: model READY na CPU, prognozy XAUUSD/BTC × M5/M15 aktualne, oznaczone SYNTETYCZNE;
* PMW-PRED-1 READY, katalog READY, historia zapisana, panel z wykresem.

**Walidacja przez API** (losowe wagi, dane syntetyczne), wynik zgodny z oczekiwaniem:
* MAE 23,6 przy 3,8 dla „ostatniej ceny”, trafność kierunku 40 % przy 67 % dla momentum, p = 0,85;
* werdykt **negatywny** z wypisanymi powodami.

## 4. Ograniczenia i niewykonane testy

* **Nie wykonano** (blokada sieci):
  * pobranie oficjalnych wag;
  * test regresji autorów na oficjalnych wagach (`TestOfficialWeights`);
  * sprawdzenie rewizji w źródle;
  * prawdziwa prognoza Kronos-small.
* **Nie wykonano** (brak Windows): `33_KRONOS_INSTALUJ.bat`, instalacja PyTorch CPU z PyPI na Windows z sumami, `runtime\python` z paczki,
  WebView2.
* **Nie wykonano** (brak GPU): ścieżka CUDA (`cu126`/`cu128`) – kod przechodzi na CPU z przyczyną, ale działanie GPU jest
  niesprawdzone.
* **Nie wykonano** (brak MT5): dane brokera (symbole, sesje, czas serwera, tick_volume / real_volume), walidacja walk-forward na Twoich
  świecach.
* **Bez dowodu skuteczności:** nie ma żadnego procentu trafności ani przewagi handlowej. Gotowość do prognozowania to nie wynik
  handlowy. Okres pretreningu może nakładać się z Twoimi danymi testowymi.
* **Ograniczenia modelu i obliczeń:**
  * prognozowane OHLC mogą mieć niespójną geometrię (model liczy kanały osobno) – panel to pokazuje, nie poprawia zamknięcia;
  * `sample_count > 1` w oryginale uśrednia próbki – nie jest używane; pasmo niepewności to osobne niezależne ścieżki, nieskalibrowane;
  * po zamknięciu świecy M5 liczenie trwa kilka sekund; w tym czasie prognoza jest „nieaktualna” (przy REQUIRED setup czeka).

## 5. Kroki na Twoim komputerze

1. Rozpakuj `PepeMarketWizard_DESKTOP_1_31_0.zip` do nowego folderu (kopia danych robi się przy pierwszym starcie), uruchom
   aplikację i połącz MT5 (DEMO).
2. Ustawienia → Mapowanie instrumentów: potwierdź symbol XAUUSD (np. `XAUUSD-`) i wybierz symbol BTC z listy kandydatów.
3. Wykresy bota → **Kronos AI Forecast** → **Zainstaluj model Kronos**. Alternatywnie: zamknij bota i uruchom `33_KRONOS_INSTALUJ.bat`.
   Czekaj na „GOTOWE”. Przy błędzie NETWORK odblokuj `pypi.org`, `files.pythonhosted.org` i `huggingface.co`.
4. **Sprawdź instalację** – oczekiwane:
   * prognoza testowa OK z czasem;
   * porównanie z wynikiem autorów PASS. DIFF przy poprawnych sumach oznacza różnicę obliczeń na Twoim CPU – podana jest jej wielkość.
5. Po zamknięciu kolejnych świec M5/M15 panel pokaże prognozy (tryb SHADOW).
6. Test oficjalnych wag w folderze `tests`:

   ```
   set MQ_KRONOS_WEIGHTS_DIR=%LOCALAPPDATA%\PepeMarketWizard\data\kronos\models
   ..\.venv_kronos\Scripts\python -m unittest test_kronos_runtime.TestOfficialWeights
   ```

7. Po kilku dniach rozliczeń kliknij **Uruchom walidację** dla XAUUSD M5 (i M15) na rachunku DEMO z historią co najmniej kilku
   tygodni. Werdykt pozytywny jest warunkiem koniecznym, nie wystarczającym. Tryb „warunek wymagany” włączaj wyłącznie świadomie.
