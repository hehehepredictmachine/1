# Raport – PepeMarketWizard 1.40.2 (poprawka instalatora modeli)

| Plik | SHA-256 |
|---|---|
| `PepeMarketWizard_DESKTOP_1_40_2.zip` (2697 plików, aplikacja Windows) | `d385d17b59ddc775acdaea174eef29abc1a9a9168817920ad4f89515a82346ec` |
| `PepeMarketWizard_1_40_2.zip` (1628 plików, folder programu) | `fa0c8d72a080ca11b1fcc3861614f9e93c9ed27c84a97dc8cd1c5f8a5d4a7bfa` |

Zgłoszenie: „nie działa installer” (bez logu). Znaleziony błąd: instalator modeli uruchamiany z aplikacji desktop dziedziczył `PYTHONPATH`
bota; pip w środowisku modelu pomijał pakiety obecne u bota w tej samej wersji („Requirement already satisfied … pyenv\…\site-packages”),
więc `.venv_granite` / `.venv_chronos2` / `.venv_kronos` / `.venv_deep` zostawało niekompletne (odtworzone: brak `scipy` w środowisku).
Poprawka: czyste środowisko dla każdego kroku instalatora. Sprawdzenie: pełna instalacja Granite TTM z zanieczyszczonym `PYTHONPATH` – OK
(pakiety, wagi z sumami, prognoza testowa, zgodność z oficjalnym API); `tests/test_installer_env.py`, testy procesu aplikacji i desktop – OK;
`verify_release.py --all` – OK. NOT RUN: Windows (brak maszyny Windows w środowisku).

---

# Raport – PepeMarketWizard 1.40.1 (poprawka startu aplikacji desktop)

| Plik | SHA-256 |
|---|---|
| `PepeMarketWizard_DESKTOP_1_40_1.zip` (2697 plików, aplikacja Windows) | `08b3a1afd8e046a667e73b0794d9ec404c0ac3e90b0c4ebb27f1ef05e63dd9b8` |
| `PepeMarketWizard_1_40_1.zip` (1628 plików, folder programu) | `0bb8d21fde580e58e7eac2170fc2b28f85a315104d166b7644cf7c2c55bcac44` |

Zgłoszenie: 1.40.0 na Windows – „silnik zakończył się podczas startu”, bez logu. Na Linuksie 1.40.0 startował (także z konfiguracją 1.39
i czystym środowiskiem z requirements-win.txt), więc przyczyna jest specyficzna dla Windows / danych użytkownika i nie została odtworzona.
Poprawki: start każdego podsystemu osobno (błąd jednego nie zabija silnika, lista w `/api/v1/health` → `start_failures`), Memory Governor
z jawnymi prototypami ctypes i bezpiecznym wyłączeniem, kod 5 + `logs/engine_crash.txt` + faulthandler, launcher pokazuje ostatnie linie
logu i obsługuje kody 3/4. Testy: `tests/test_start_resilience.py` (3), testy Go desktop (w tym atrapa silnika padającego przy starcie),
`verify_release.py --all` OK, start z rozpakowanej paczki: wersja 1.40.1, `start_failures: []`.
NOT RUN: Windows (brak maszyny Windows w środowisku) – jeśli start dalej się nie uda, okno błędu pokaże przyczynę z logu.

---

# Raport końcowy – PepeMarketWizard 1.40.0 (Granite TTM zamiast FinCast, Memory Governor 16 GB, nowy WTC$PEPE, optymalizacja UI)

| Plik | SHA-256 |
|---|---|
| `PepeMarketWizard_DESKTOP_1_40_0.zip` (2696 plików, aplikacja Windows) | `a277bcf301ae2eff307f561bacb0ac35d787027063dfe77348b7bb1d649ed23f` |
| `PepeMarketWizard_1_40_0.zip` (1627 plików, folder programu) | `bff296075624e782546a158c18fc2d59950354142b0880831d257a860d67d91b` |
| `Instrukcja_Instalacja_Modele_Trening_PepeMarketWizard.pdf` (zaktualizowana: Granite TTM, Memory Governor) | – |

`verify_release.py --all`: OK (ścieżki, manifest, sekrety, .sha256). Paczki bez wag, `.venv_*`, danych rachunku i plików FinCast.
Start z rozpakowanej paczki (demo): wersja 1.40.0; konfiguracja v14 → v15 (`resources` = LOW_MEMORY_16GB, kopia `config.v14.bak.json`);
ustawienia modeli z wpisem FinCast → modele `chronos2`, `granite_ttm`, FinCast w `retired`, kopia `settings.v139.bak.json` + historia zmian.
Punkt przywracania kodu: tag `pre-1.40-restore-point` (1.39.0).

## Kryteria zakończenia (masterprompt)
| Kryterium | Stan |
|---|---|
| FinCast nie działa w aktywnym pipeline | DONE – nie jest instalowany, ładowany ani planowany; API zwraca MODEL_RETIRED; historia zachowana |
| Granite TTM – rzeczywista inferencja | DONE – oficjalne wagi (sumy SHA-256), parytet z oficjalnym API PASS, testy na prawdziwych wagach |
| Kronos i Chronos-2 nadal działają | DONE – testy na prawdziwych wagach Chronos-2 OK; Kronos zmierzony w pomiarze RAM (80 prognoz, 0 błędów) |
| Prognozy w ModelHub i u odbiorców strategii | DONE – kontrakt PMW-PRED-2, koordynator ACTIVE, odbiorniki SH, porównanie modeli, panele (testy) |
| Wspólny harmonogram chroni pamięć | DONE – Memory Governor: progi 75/80/85 %, jeden slot ciężki, STALE zamiast wartości, bramka treningu (testy) |
| Tryb CPU-only | DONE – cały pomiar i testy bez GPU; CUDA tylko gdy działa, sterowniki nie są instalowane |
| Brak nowych błędów krytycznych | DONE – pełna regresja 1348 testów, 23 pominięte (brak torch w interpreterze testów), 1 test UI z za krótkim limitem czasu poprawiony i powtórzony OK |
| Konfiguracja 16 GB zmierzona i opisana | DONE – docs/MIGRACJA_FINCAST_GRANITE_1_40_PL.md §6 (komputer 16 GB, 4 vCPU) |
| Możliwość cofnięcia | DONE – ROLLBACK 0e, kopie konfiguracji, tag git |
| Brak fikcyjnych prognoz / wyników | DONE – Granite punktowy (bez kwantyli i świec), WTC bez wartości demo, wyniki walidacji ujemne opisane wprost |

## Pomiary
* Walk-forward XAUUSD (HistData, Q4 2025, dane po publikacji modeli): MAE względem modelu naiwnego – Granite R2 512-96 −9 %, Chronos-2 −2…−3 %,
  Kronos-base −29…−59 %; trafność kierunku 41–57 % bez istotności. **Żaden model nie pokonał prognozy „ostatnia cena”** → rola OBSERVE.
* Dotrenowanie Granite (M5): test MAE 8,14 vs bazowy 8,44 vs naiwny 7,83 – lepszy od bazowego, nie od naiwnego.
* RAM (16 GB): backend 431 MB, Granite 346 MB (p50 3,4 ms), Chronos-2 600–835 MB (p50 79 ms), Kronos 672–1062 MB (p50 6,9 s CPU);
  3 modele sekwencyjnie 60 świec M5 + M15: 0 błędów, szczyt 11,7 % RAM, suma modeli 2,0 GB. FinCast wymagał ok. 8 GB przy ładowaniu.
* UI (Chromium bez GPU): menu Galaxy 0,7 → ~34 FPS, WTC 47–58 FPS przy nowym układzie z filmem tła (docs/WYDAJNOSC_UI_1_40_PL.md).

## NOT RUN (środowisko)
Windows i prawdziwy MT5 (symulator), GPU / CUDA, porównanie strategii po kosztach na Twojej historii MT5 (wymaga eksportu i
`39_PAKIET_20_WALIDACJA.bat`), GUI WebView2. Dane walidacyjne to publiczny zbiór XAUUSD, nie Twój broker.

Nie otwierano transakcji i nie zmieniano trybu rachunku. Ustawienie LIVE od startu z 1.39 pozostaje bez zmian.

---

# Raport końcowy – PepeMarketWizard 1.39.0 (LIVE od startu, GARCH w HG09, intro, menu Galaxy V2, WTC PEPE 2.1, instrukcja PDF)

**Paczki 1.39.0:**

| Plik | SHA-256 |
|---|---|
| `PepeMarketWizard_DESKTOP_1_39_0.zip` (2685 plików, aplikacja Windows) | `4bdc7842deee6004d1e0e80cd66d01e680dbf58abcfa514d7936bde16c34818c` |
| `PepeMarketWizard_1_39_0.zip` (1616 plików, folder programu) | `0cea51a0df2caddc19e41ae9ef823d37891d2478c15632392e9849d1e5825f37` |
| `Instrukcja_Instalacja_Modele_Trening_PepeMarketWizard.pdf` (14 stron; także w paczce: `docs/`) | – |

`tools/verify_release.py --all`: OK dla obu (ścieżki, manifest, sekrety, .sha256). Paczki bez wag modeli, środowisk `.venv_*`, danych
rachunku i historii. Start z rozpakowanej paczki (backend demo): wersja 1.39.0, konfiguracja zmigrowana do v14 (`execution.start_mode =
AUTO_LIVE`, `live_autobind = true`), symulator pozostaje w PAPER (dane syntetyczne nigdy nie idą LIVE), zasoby `/assets/galaxy/*` serwowane
(WebP, MP4, GIF), katalog 20 wariantów + stan GARCH (`NOT_TRAINED` – brak modelu w czystej instalacji). Paczka 1.38.0 nie została nadpisana.

## Co zrobiono (polecenie: LIVE, bez ograniczeń, GARCH, PDF, menu z paczek ZIP)

| Zadanie | Stan | Uwagi |
|---|---|---|
| Tryb LIVE od startu | DONE | `start_mode = AUTO_LIVE`, autowiązanie z rachunkiem REAL przy pierwszej decyzji (`LIVE_AUTOBIND`) |
| Zdjęcie ograniczeń (wybór: „bramki walidacji”) | DONE | VALIDATED, skalibrowany model, znana prowizja, REDUCE/NETTING → ostrzeżenia. **Zostały**: STOP, limity ryzyka, spread, deduplikacja, uzgadnianie MT5, wymóg REAL, ścieżka główna |
| Model GARCH | DONE | rodzina VOL_GARCH → sigma PMW_HG09 (`volatility_method`), przełącznik w panelu Pakiet 20, bez cichego zastępstwa (`GARCH_NOT_READY`), replay `--garch-json` |
| Instrukcja PDF (instalacja bota, modeli, trening) | DONE | `tools/make_install_guide.py`; polecenia sprawdzane testem `test_install_guide.py`; podręczniki admin/klient z rozdziałem 1.39 |
| Intro startowe (paczka ALL_IN_ONE) | DONE | 8,5 s, slogan dokładny, Esc / POMIŃ, Ctrl+Alt+B, ograniczone animacje, twardy limit, nie blokuje |
| Menu Galaxy V2 + edytor (paczka ALL_IN_ONE) | DONE | 7 planet, 21/21, emitery, błyskawice, edytor z trasą planety, JSON; planety → prawdziwe ekrany; status z backendu |
| WTC PEPE 2.1 Chart Lab + SVP (paczka WTC 2.1) | DONE | na prawdziwych świecach `/api/v1/candles`; elementy demo oparte na danych syntetycznych nieprzeniesione |

## Testy i build

| Zestaw | Wynik |
|---|---|
| Pełna regresja `tools/run_tests.py` | 1333 testy, 22 pominięte (brak PyTorch / modeli w tym interpreterze); 4 niepowodzenia – asercje `config_version == 13` w starych testach migracji (oczekiwane po v14) – poprawione, 17/17 powtórzone OK |
| Nowe: `test_live_start`, `TestGarchHG09` (`test_sh_pack`), `test_ui_galaxy` (6), `test_ui_wtc_chartlab`, `test_chartlab_calc` (Node), `test_install_guide` (4), `test_ui_sh_pack` (przełącznik HG09) | OK |
| Testy menu przeniesione na `#/neural-city` (`test_ui_neural_city`, `test_ui_cult`, `test_ui_towers`, `test_ui_wizard`, `test_ui_pages`, `test_ui_interface_129`, `test_ui_pmw133`) | OK |
| `tsc --noEmit`, `npm run build`, `go test` aplikacji desktop, go-winres (wersja 1.39.0.0 w EXE), kontrola requirements Windows | OK |
| Rozdzielczości menu 1366×768 / 1440×900 / 1920×1080 | bez poziomego przewijania, wszystkie planety w kadrze, bez błędów JS, bez zleceń / zmian trybu |

## Ograniczenia (uczciwie)

* **LIVE oznacza prawdziwe pieniądze.** Żaden z 20 wariantów nie ma walidacji OOS na Twoich danych (NOT_VALIDATED) – w 1.39 to już
  tylko ostrzeżenie. Do handlu bot nadal potrzebuje wybranej ścieżki głównej (ACTIVE / SH) i ustawionych limitów ryzyka.
* Brak Windows i terminala MT5 w środowisku budowania: AUTO_LIVE i autowiązanie rachunku przetestowane na atrapach terminala i
  symulatorze, nie na prawdziwym rachunku. Pliki EXE niepodpisane.
* GARCH wymaga wytrenowania i aktywacji VOL_GARCH na historii MT5 – w czystej instalacji HG09 z `VOL_GARCH` zwraca `NO_DATA`.
* SVP Chart Lab to przybliżenie z OHLC (wolumen rozłożony na High–Low świecy), sesje w stałych godzinach UTC; nie footprint / order flow.
* Intro i menu w przeglądarce bez GPU renderują się wolniej (canvas z poświatą) – na komputerze z GPU płynnie; menu wstrzymuje
  rysowanie, gdy intro jest na ekranie.

Nie otwierano transakcji i nie zmieniano trybu żadnego rachunku.

---

# Raport końcowy – PepeMarketWizard 1.38.0 (pakiet 20 strategii XAUUSD: 10 HEDGING + 10 SCALPING)

**Paczki 1.38.0:**

| Plik | SHA-256 |
|---|---|
| `PepeMarketWizard_DESKTOP_1_38_0.zip` (2635 plików, aplikacja Windows) | `61a93ade75563da4a730b1c2a4ff35e4a7d06e481b2d701780a5713c6903ecb5` |
| `PepeMarketWizard_1_38_0.zip` (1566 plików, folder programu) | `3e0dd8ccc164236cad5fe62fd055bccab7983c711b0855e52ae05e67e61620f8` |

`tools/verify_release.py --all`: OK dla obu (ścieżki, manifest, sekrety, .sha256). Paczki bez wag modeli, środowisk `.venv_*`, danych
rachunku, historii i raportów walidacji. Start z rozpakowanej paczki (backend demo): wersja 1.38.0, katalog 20 wariantów
(PMW-SH-PACK-2.0.0), migracja 0027 zastosowana. Wejściowa paczka 1.37.0 nie została nadpisana.

## Co działa end-to-end

Feed MT5 (zamknięte świece M1/M3/M5/M15/H1) → cykl SH po każdej zamkniętej M1 (niezależnie od otwarcia panelu) → 20 detektorów
(BUY + lustrzany SELL, wspólna generacja cech) → solver dwóch TP i RR netto / RR koszyka → odbiorniki modeli (role istniejące) →
arbitraż (jedno wejście na ekspozycję) → silnik ryzyka z profilem wariantu → DecisionCoordinator → IntentLedger/RiskBook → executor SH w
bieżącym trybie (SIGNALS: zero zleceń, PAPER: jawne fille) → plan z planowanymi TP1/TP2 bez BE → zarządzanie koszykiem HG polityką
wariantu (hedge z intencją HEDGE i rezerwacją, limit po partialu, timeout = wyjście koszyka) → plan PMW-PLAN-2 → panel „Pakiet 20
strategii”, warstwa wykresu „Pakiet 20” (strzałki, Entry/SL/TP1/TP2), PEPE$SIGNAL z tożsamością wariantu i TF, statystyki per wariant →
replay/walidacja na eksporcie (CLI, zadanie runnera `sh_pack`, `39_PAKIET_20_WALIDACJA.bat`).

## 20 strategii

| ID | Implementacja | Testy | Walidacja skuteczności |
|---|---|---|---|
| PMW_HG01–HG10 | IMPLEMENTED (detektor + plan + polityka hedge) | TESTED (mechanika; polityki: HG03 pełny scenariusz, wszystkie – teksty i ograniczenie straty, replay) | NOT_VALIDATED |
| PMW_SC01–SC10 | IMPLEMENTED (detektor + plan) | TESTED (mechanika) | NOT_VALIDATED |

Szczegóły per ID: `docs/strategies20/TEST_REPORT.md`; reguły: `STRATEGY_SPECIFICATIONS.md`; integracja: `INTEGRATION_MAP.md`;
RR i jednostki: `RISK_AND_UNITS.md`; instrukcja: `RUNBOOK_PL.md`; źródła: `RESEARCH_AND_SOURCES.md`; rollback: `ROLLBACK.md` (0c).

## Testy i build

| Zestaw | Wynik |
|---|---|
| `test_sh_pack` (24) + `test_ui_sh_pack` (1) | OK |
| Pełna regresja `tools/run_tests.py` | 1314 testów, 22 pominięte; 6 błędów z jednej przyczyny (stary kontrakt `arbitrate` w testach) – naprawione, 37/37 powtórzone OK; po ostatnich zmianach 155 testów z dotkniętych zestawów OK |
| `npm run typecheck`, `npm run build`, `go test` aplikacji desktop, kontrola requirements Windows | OK |
| Zadanie runnera `sh_pack` (demo), replay CLI (40 000 M1 syntetycznych, 52 s) | UKOŃCZONE; werdykty NOT_VALIDATED (dane syntetyczne) |
| Wydajność cyklu pakietu | offline p50 26 ms / p95 33 ms; w działającym bocie demo p50 337 ms / p95 738 ms (raz na M1, 4 vCPU) |

## Ograniczenia

* Brak historii MT5 użytkownika → żaden wariant nie ma walidacji OOS (NOT_VALIDATED). Pakiet nie jest „gotowy do zyskownego handlu”;
  AUTO_LIVE dla wariantu wymaga raportu VALIDATED na `REAL_USER_DATA`.
* Warianty HG potrzebują ~42 dni historii H1 do rozgrzewki (EMA200 × 5) – przy krótszej historii pozostają WARMING_UP.
* Brak Windows i terminala MT5 w środowisku budowania (AUTO_DEMO/AUTO_LIVE nietestowane na prawdziwym terminalu); pliki EXE niepodpisane.
* Prowizja nieznana → plan hipotetyczny ze scenariuszem kosztowym (nie NET_VALIDATED / READY_TO_EXECUTE); swap niemodelowany.
* REDUCE na rachunku NETTING dla pakietu niewłączony (HG na NETTING = blokada z powodem); wariant GARCH dla HG09 – nie zaimplementowany jako
  podmiana. DSR/PBO – wymagają realnych serii; raport replayu pokazuje wszystkie próby.

Nie otwierano transakcji i nie zmieniano trybu rachunku.
