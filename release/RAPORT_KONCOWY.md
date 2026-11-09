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
