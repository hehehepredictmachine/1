# Raport końcowy – PepeMarketWizard 1.34.2 (Neural City V7.0, launcher JOIN THE CULT, poprawki instalacji)

**Paczki 1.34.2:**

| Plik | SHA-256 |
|---|---|
| `PepeMarketWizard_DESKTOP_1_34_2.zip` (2520 plików) | `4c2956005671c0e6089d9291f1f49410dcfe06f20851c132cfbceaebd79f7cc0` |
| `PepeMarketWizard_1_34_2.zip` (1451 plików) | `0874f1924904c207b280ea04328b0aba36106c403828a4f0ee111f842c9f7d36` |

`tools/verify_release.py --all` daje OK dla obu.

**Zakres:**
* 1.34.0 – menu główne Neural City V7.0 i launcher JOIN THE CULT (TASK 001). Opis: `docs/NEURAL_CITY_I_LAUNCHER_1_34_PL.md`.
* 1.34.1 – instalacja na Windows: dodane brakujące zależności statsmodels (`formulaic`, `interface-meta`, `wrapt`). Błąd był od
  1.33.0, a zgłosił go użytkownik ze zrzutem „[BLAD] Instalacja pakietow”.
* 1.34.2 – przycisk Studio na pasku narzędzi Neural City (regresja wykryta przez końcowy test UI).

**Testy:**

| Co | Wynik |
|---|---|
| Końcowa regresja na kodzie 1.34.0 | 89 plików bez UI (1090 testów, 12 pominiętych) – wszystkie OK; 19 plików UI (132 testy) – 18 OK, `test_ui_pmw133` 1 błąd |
| Błąd `test_ui_pmw133` | brak przycisku Studio w nowym menu – naprawione w 1.34.2; `test_ui_pmw133`, `test_ui_neural_city` i `test_ui_cult` ponownie 17/17 OK |
| `test_families_u4` + `test_config_v13` z przypiętymi wersjami 1.34.1 | 20/20 OK |
| `tools/check_requirements_win.py` (symulacja instalacji Windows x64, markery Windows, sumy, Python 3.13 i 3.12) | 4 pliki × 2 wersje OK; stara lista z 1.34.0 odtwarza błąd użytkownika (`formulaic`) |
| Start z obu paczek 1.34.2 (ścieżka ze spacjami i polskimi znakami, istniejąca konfiguracja v12, Studio z menu bota, restart) | 14/14 PASS każda |
| `go test -count=1`, `go vet` (windows) | OK |

**Nie sprawdzono:**
* okna Windows (WebView2) ani instalacji na prawdziwym Windows – tylko symulacja instalacji i start plików aplikacji przez Pythona Linux;
* MT5.

Menu działa w trybie 2.5D (bez modeli 3D wież i riga Pepe – lista brakujących zasobów jest w dokumencie Neural City).

---

# Raport końcowy – PepeMarketWizard 1.33.0 (wszystkie aktualizacje)

**Zadanie:** wdrożenie pakietu `PepeMarketWizard_Prompty_Wdrozenia_Wszystkich_Aktualizacji.zip` (SHA-256 `6ca0e387…a3dc99`): START + specyfikacje
AUD (audyt, 15 rodzin modeli, trening), IND (wskaźniki, DXY, plany Scalp/Hedge, SVP), STU (Data & Training Studio), ARC (architektura
decyzji). Baza: 1.32.0 (`5e5d82a`). Gałąź `claude/masterquo-ai-bot-mt5-f7uaht`. Paczki zbudowane z commitu
`e365c2005fff27b3d7d823ec1e5ad769b4541842`.

**Środowisko:** 2026-11-07, kontener Linux 6.18 x86_64 (bez GPU), Python 3.13.18, Node 22, Go 1.24.7, Chromium. Brak Windows, terminala MT5 i
konta brokera: zamiast terminala działa symulator (dane SYNTETYCZNE). Nie złożono żadnych zleceń.

**Uwaga o źródle wymagań:** po U5 kontener został zresetowany i rozpakowane specyfikacje przepadły. Etapy U6–U8 (ARC, panel, wydanie) wykonałem
według notatek z pierwszego czytania. Jeśli chcesz porównania punkt po punkcie z oryginałem (np. numeracji scenariuszy testowych 1–13),
prześlij pakiet ponownie.

## 1. Co wdrożono i jak jest połączone
Pełna macierz: `docs/INTEGRATION_MATRIX.md` + `integration_manifest.json` (generator `tools/integration_matrix.py`). Każdy wiersz zawiera
wymaganie, moduł, podłączenie w Runtime, odbiorców i testy. Generator sprawdza ścieżki, trasy API i pliki testów: **37/37 wymagań
zaimplementowanych i podłączonych**, braków 0.

| Spec | Najważniejsze | Runtime / analiza / strategie / panel / trening |
|---|---|---|
| AUD | <ul><li>PMW-PRED-2</li><li>M3 w całym łańcuchu</li><li>`dxy_missing` z rzeczywistej dostępności</li><li>Kronos REQUIRED z odciskiem</li><li>15 rodzin PMW-FAM-1 z magazynem artefaktów, aktywacją, rollbackiem i rolami</li><li>`.venv_deep`</li><li>trainhub RF/SVM/XGB i profile</li></ul> | FamilyService w Runtime → SH (kontekst + ASSIST), ACTIVE (węzeł MODELS), agent, Centrum treningu „Rodziny modeli 1.33” |
| IND | <ul><li>PMW-IND-1: AVWAP, spread vs sesja, semiwariancja, XAUUSD×DXY bez forward-fill, OFI/arkusz, profil sesji</li><li>PMW-PLAN-1 Pepe Scalp / Hedge Plan</li><li>PMW-SVP-1 (profile, strefy MANUAL/ALGORITHM/AI)</li></ul> | IndicatorService / SVPService w Runtime → kontekst ACTIVE, SH (OBSERVE), narzędzia agenta, `#/dxy`, `#/svp`, warstwy Scalp Plan / Hedge Plan / AVWAP / SVP na każdym wykresie |
| STU | <ul><li>osobna aplikacja Studio: proces, port 8780, blokada O_EXCL z heartbeat, wspólna blokada eksportu z botem</li><li>rejestr 72 zadań, kolejka</li><li>paczki per zadanie z atomowymi etapami</li><li>test ładowania w czystym procesie</li><li>import do bota jako kandydat (rollback, inbox)</li><li>`PepeTrainingStudio.exe`</li></ul> | przycisk **Studio** ze stanem (górny pasek, menu CULT) uruchamia osobny proces; `process_inbox()` przy starcie bota |
| ARC | <ul><li>10 kontraktów</li><li>jeden DecisionCoordinator obu ścieżek</li><li>role OBSERVE / ASSIST / REQUIRED</li><li>DecisionRecord (migracja 0025)</li><li>atomowa rezerwacja limitów portfela obu ścieżek</li><li>intencje wykonania z deduplikacją i rozliczaniem UNKNOWN</li><li>replay</li></ul> | engine / gateway / SH / manager dzielą jeden koordynator; panel `#/decyzje` |

Execution Lock **nie** został przywrócony. Tryby SIGNALS/PAPER/AUTO DEMO/AUTO LIVE, STOP nowych wejść, limity użytkownika i wymagania
brokera działają bez zmian.

## 2. Modele (15 rodzin + adapter)
Walidacja kontrolna: dane SYNTETYCZNE o znanej strukturze, profil smoke (`tools/validate_families_synthetic.py`). Sprawdza potok i bramkę,
**nie rentowność**. Szczegóły: `docs/RAPORT_WALIDACJI_MODELI.md`, karty modeli: `MODEL_CARDS/families/`.

| Rodzina | Zadanie | Środowisko | Odbiorcy | Trening → zapis → ładowanie → predykcja | Bramka (smoke, SYNTHETIC) |
|---|---|---|---|---|---|
| TS_ARIMA | log-zwrot H1/3/5 (M5) | główne | SH, panel, agent | OK | APPROVED |
| TS_SARIMAX | log-zwrot H1 + kalendarz | główne | SH H1 | OK (po naprawie A8) | APPROVED |
| VOL_GARCH | zmienność | główne (`arch`) | SH / ryzyko | OK | APPROVED |
| MICROSTRUCTURE | stan arkusza 10 s | główne | SH jakość wejścia | OK | APPROVED |
| PAIR_COINT | relacja pary | główne (wymaga `families.pairs`) | SH | OK | APPROVED |
| STATARB | koszyk ≥3 | główne (wymaga `families.basket`) | panel | OK | APPROVED |
| KALMAN_LS | poziom + nachylenie | główne | SH | OK | APPROVED |
| BREAKOUT | stan wybicia | główne | SH | OK | APPROVED |
| TH_RF / TH_SVM / TH_XGB | kierunek po kosztach | trainhub | SH / panel | `test_trainhub` 22 OK | (trainhub) |
| SEQ_LSTM / SEQ_GRU | rozkład kierunku H6 | `.venv_deep` | SH | OK (rzeczywisty trening torch) | VALIDATION_FAILED – budżet smoke; zgodnie z projektem bramka nie dopuszcza |
| RL_PPO | propozycja akcji | `.venv_deep` (SB3) | panel / SH kontekst | OK | VALIDATION_FAILED (smoke) |
| NLP_SENTIMENT | sentyment nagłówków | główne / lokalny transformer | SH, agent | OK | APPROVED |
| SEQ_GRU_EVENT (adapter) | zdarzenia MM | centrum MM | SH | `test_mm_*` OK | (MM) |

Domyślnie każda rodzina ma rolę OFF albo SHADOW, a `decision.required_models` jest puste. Rola ASSIST wymaga walidacji APPROVED na
Twoich danych REAL.

## 3. Testy – komendy i wyniki (końcowy przebieg na kodzie wydania)

| Komenda | Wynik |
|---|---|
| 89 plików testów bez UI (`python -m unittest <plik>`, 3 równolegle) | **89/89 OK**, 1090 testów, 12 pominiętych: 8 Kronos bez osobnego PyTorch, 2 `mm_integration`, 2 `train_all` |
| 21 plików UI (Chromium, serwer `--demo`, 3 kolejki bez kolizji portów) | **21/21 OK**, 127 testów, w tym nowy `test_ui_pmw133` (strony `#/dxy`, `#/svp`, `#/decyzje`, sekcja rodzin, 4 warstwy wykresu bez żądań zapisu, przycisk Studio, uruchomienie Studio z bota) |
| nowe w 1.33 | `test_integration_u1` 9, `test_indicators_u2` 30, `test_plans_svp_u3` 21, `test_families_u4` 19, `test_studio_u5` 7, `test_decision_arc_u6` 18, `test_config_v13` 1 – OK |
| `desktop`: `go test -count=1 ./...`, `GOOS=windows go vet ./...`, `gofmt -l` | OK |
| `npm run build` (TypeScript + Vite) | OK |
| `tools/migration_check.py --old-ref 5e5d82a` (z `MQ_FAKE_MARKET_ALWAYS_OPEN=1`, bo symulator ma weekend) | **13/13 PASS**: 1.33 na danych 1.32 (konfiguracja, migracje, strefy), powrót na kopii, kopia `config.v12.bak.json`, 1.32.0 na danych po 1.33 z przywróconą kopią |
| `tools/verify_release.py --all` | OK dla obu paczek |
| start z wygenerowanych paczek (`pkg_launch`) | **13/13 PASS dla każdej paczki** – szczegóły w sekcji 5 |

Zaktualizowane oczekiwania starych testów, wszystkie wynikające z zamierzonych zmian:
* M3 w rejestrze TF (`test_ui_pages`, `test_ui_signal_card`);
* kontrakt PMW-PRED-2 (`test_ui_training_center`);
* lista migracji z 0025 (`test_risk_execution`);
* config v13 (`test_relaxed_gates`, `test_execution_lock_withdrawn`, `test_volzones`).

**Błędy znalezione i naprawione w trakcie** (pełna lista A1–A10: `docs/AUDYT_I_NAPRAWY_MODELI.md`):
* **SARIMAX nie zbiegał na H1.** Model był BLOCKED, a ARIMA często nie zbiegała. Poprawka: zwroty skalowane do wariancji 1.
* **Powrót do 1.32 kończył się odmową startu.** 1.32 nie przyjmuje `config.json` zapisanego przez 1.33. Poprawka: konfiguracja v13
  zostawia nietknięty plik 1.32 jako kopię.
* **Studio szukało danych bota w innym katalogu niż bot w Windows.**
* **Limit pozycji portfela dało się przekroczyć,** gdy obie ścieżki działały naraz.
* **Pętla mostu MT5 przerywała się na nowym interwale M3** (regresja z U1).

## 4. Replay: stara (1.32) i nowa (1.33) logika decyzji
`python -m masterquo.decision.replay [--db kopia.sqlite] [--required RODZINA]`:

| Scenariusz | 1.32 | 1.33 |
|---|---|---|
| wyścig obu ścieżek: 6 wejść w jednym oknie wysyłki, `max_open_positions = 2` | **6 przechodzi** (limit przekroczony) | **2 przechodzi**, 4 × `PORTFOLIO_MAX_OPEN_POSITIONS_RESERVED` |
| zapisane decyzje bez ról ASSIST/REQUIRED (test: 3 decyzje; baza z testu paczki: 2) | – | identyczne werdykty, 0 zmian |
| te same decyzje z REQUIRED bez prognozy (test) | ALLOWED | BLOCKED `MODEL_REQUIRED_UNAVAILABLE` (2 z 2 wejść) |

W tym środowisku zapisanych decyzji było mało (krótkie przebiegi demo). Zalecam replay na kopii Twojej bazy z MT5, żeby zobaczyć wpływ
konkretnej roli REQUIRED przed jej włączeniem.

## 5. Paczki 1.33.0 i start z paczki

| Plik | Rozmiar (B) | SHA-256 |
|---|---|---|
| `PepeMarketWizard_DESKTOP_1_33_0.zip` (2497 plików: `PepeMarketWizardDesktop.exe`, `PepeTrainingStudio.exe`, Python 3.13.17 dla Windows, program) | 46 628 131 | `147a72c54b5dde772e8386d8038310b97b040823f62ee20466533db32060961a` |
| `PepeMarketWizard_1_33_0.zip` (1428 plików programu) | 25 947 114 | `cf85dc32d97e6177367eb18e35e190068bb835211645b85d00b439b95dc025da` |
| `Instrukcja_Administrator_PepeMarketWizard.pdf` (11 stron, rozdziały 4b i 6 dla 1.33) | 956 457 | `c53d66eb34dc719d14de4457dfa9c15a165e0e03840bbdac363be4ee23c42201` |
| `Instrukcja_Klient_PepeMarketWizard.pdf` (7 stron, rozdział 3b dla 1.33) | 863 585 | `7ac278d8b23e7e144bb0072211f55eaec146ab8b562ee322217bcbfcc5651379` |

`MANIFEST_SHA256.txt` (1428 plików): `1b114fdbecf6eb185f772b59be19f98a1ad5d6f67b7ad89749265d9b12a97d7f`.
Zasoby EXE mają wersję 1.33.0.0. Pliki `PepeMarketWizardDesktop.exe` i `PepeTrainingStudio.exe` to różne pliki binarne (tryb ustawiany
przy linkowaniu).

**Start z wygenerowanej paczki** (obie paczki rozpakowane do ścieżki „…/Pepe Market Wizard 1.33 (test)/…”). Folder danych „Dane użytkownika
z 1.32” zawierał istniejącą konfigurację v12 (port, limity, mapowanie). Wynik dla każdej paczki **13/13 PASS**:
* wersja 1.33.0;
* konfiguracja zachowana;
* v13 i `config.v12.bak.json` równy oryginałowi;
* migracja 0025;
* rekordy koordynatora decyzji;
* 16 rodzin modeli;
* `index.html` i `studio.html`;
* Studio uruchomione z menu bota jako osobny proces (health `PepeTrainingStudio`);
* restart: ten sam tryb i konfiguracja, kopia v12 nienadpisana, rekordy decyzji zachowane.

Paczkę DESKTOP uruchomiono plikami aplikacji przez Pythona Linux. Samego EXE z oknem WebView2 nie da się tu uruchomić (patrz sekcja 6).

## 6. Aktualizacja, rollback i czego nie sprawdzono
* **Aktualizacja i powrót:** `docs/AKTUALIZACJA_1_33_PL.md` (skrót w `ROLLBACK.md` §0 i w instrukcji administratora, rozdział 6).
  * Rollback do 1.32: zamień `config.json` na `config.v12.bak.json`. Baza może zostać, bo migracja 0025 jest addytywna, a 1.32 ignoruje
    nowe tabele.
  * Sprawdzone narzędziem `migration_check` (patrz sekcja 3).
* **Nie sprawdzono (brak zasobu w środowisku):**
  * okna Windows (WebView2) obu EXE ani pierwszej instalacji zależności na Windows; sprawdzono: kompilację krzyżową, `go vet`, testy Go
    trybu studio, start plików aplikacji z paczki;
  * rzeczywistego MT5: arkusza zleceń brokera, symbolu DXY, eksportu MT5_DIRECT pełnej historii, czasu serwera;
  * treningu na Twoich danych REAL (oceny jakości i rentowności modeli) oraz profili research/full dla LSTM/GRU/PPO;
  * wydajności `.venv_deep` na Windows (testowane na Linux CPU, torch 2.14).
* **Weekend:** w sobotę symulator jest zamknięty, a w świeżym folderze danych przesunięcie zegara serwera nie jest znane, więc wykresy i
  wskaźniki w demo pokazują NO_DATA / WARMUP. Tak jest zaprojektowane (to nie jest błąd). Testy wymagające rynku używają
  `MQ_FAKE_MARKET_ALWAYS_OPEN=1`.
