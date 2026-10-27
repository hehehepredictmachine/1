# RUNBOOK – PepeMarketWizard 1.15

## Uruchomienie
1. Rozpakuj `PepeMarketWizard_TRENING_XAUUSD_BTCUSDT.zip` (wersja 1.15.0; suma SHA256 w pliku `.sha256` obok ZIP). Dane z wcześniejszej wersji (`data/`) zostają.
   - Konfiguracja migruje się sama do wersji 11.
   - XAUUSD dostaje symbol, który był wpisany wcześniej (domyślnie `XAUUSD-`).
   - Od 1.24 konfiguracja migruje do wersji 12: Execution Lock wycofany; wstrzymywany dotąd tryb AUTO → PAPER (wybierz ponownie).
2. Uruchom `03_START_MASTERQUO.bat` (MT5 musi być uruchomiony i zalogowany).
3. Pulpit pokazuje:
   - aktywo i symbol brokera;
   - wiek notowania, reżim i sesję;
   - kartę scenariusza;
   - aktywność modelu. Bez artefaktu: „Sieć nieaktywna”.

## Aktywa
- **1.14.1:** symbole nie są blokowane. Bot używa symboli z Twojego rachunku i sam dobiera brakujący symbol XAUUSD/BTC z Market Watch. W Ustawieniach → Aktywa możesz wskazać inny („Użyj”).
- Ustawienia → Aktywa:
  - XAUUSD jest wstępnie przypisane do Twojego symbolu, a metadane są sprawdzane przy połączeniu;
  - konflikt metadanych (np. inny kontrakt) blokuje tylko to aktywo.
- BTC: przycisk „Szukaj kandydatów”, potem „Potwierdź” przy właściwym symbolu. Program sam niczego nie wybiera.
- Przełącznik XAUUSD/BTC jest w górnym pasku. Po przełączeniu bridge wczytuje historię nowego symbolu, a panel czeka na nowe dane i nie pokazuje starych.

## Trening i badania
- **1.15 – instalatory treningu:** zacznij od `START_TUTAJ_TRENING_PL.md`.
  - Kolejność: `INSTALUJ_TRENING.bat` → `DIAGNOSTYKA_TRENINGU.bat` → `00_TRENING_START.bat` (albo `TRENUJ_XAUUSD.bat` / `TRENUJ_BTCUSDT.bat` / `TRENUJ_OBA.bat`).
  - Wszystkie launchery, `22_TRENUJ_WSZYSTKIE_MODELE.bat` i panel „Modele i trening → Trening XAUUSD / BTC” używają jednego mechanizmu.
  - Wynik: raport HTML/JSON w `data/training/runs/<run>/`. Każde zadanie ma trzy statusy: wykonanie / jakość / integracja.
  - Aktywowane są tylko modele dopuszczone walidacją. Rollback działa per instrument i rodzina.
- Modele i trening → wybierz rodziny → „Uruchom badanie dla <aktywo>”: pojedyncze badanie lab z buforu bota (postęp, log, Anuluj).
- Artefakt lab to zawsze model oceniony na danych rozwojowych.
  - Rola „shadow”: tylko gdy przeszedł holdout.
  - Rola „badawczy”: pozostałe modele.
  - Rola „techniczny”: dane syntetyczne.
- Badania i walidacja: werdykt, foldy, kontrole, rejestr prób, holdout, macierz M01–M42.

## Moduły IQ / PAL / SAR (PMW-UPD-02)
- Instrukcja: `docs/MODULY_IQ_PAL_SAR_PL.md`, launcher `MODULY_IQ_PAL_SAR.bat`, panel: Modele i trening → „Moduły IQ / PAL / SAR”.
- Standard gotowości modułów: `docs/STANDARD_MODULOW_PL.md`; rejestr postępu aktualizacji: `docs/updates/update_registry.json`.

## Scalp ML – wynik netto cyklu (PMW-UPD-03)
- Instrukcja: `docs/SCALP_ML_NETTO_PL.md`, launcher `24_SCALP_ML.bat`, panel: Modele i trening → „Scalp ML – wynik netto cyklu”.
- Model nigdy nie jest wybierany automatycznie; OBSERVE / SHADOW_GATE ręcznie, bez wpływu na zlecenia.

## Neural Scalp System (PMW-UPD-04)
- Instrukcja: `docs/NEURAL_SCALP_SYSTEM_PL.md`, launcher `23_NEURAL_SCALP.bat`, panel: Pulpit → „Neural System — Scalping”, Modele i trening → Neural System.

## Scalping MTF (PMW-UPD-05)
- Instrukcja: `docs/SCALPING_MTF_DASHBOARD_PL.md`, panel: Wykresy → Scalping MTF (`#/scalp-mtf`); działa bez modeli.

## Boksy sesji i heatmapa likwidacji (PMW-UPD-06)
- Instrukcja: `docs/indicators/LIQUIDATION_AND_SESSION_SWEEPS_PL.md`, launcher `25_LIQUIDITY.bat`, panel: Wykresy MTF → „Boksy sesji”, „Heatmapa likwidacji”.
- Klucz CoinGlass wpisujesz lokalnie w panelu (SecretStore) albo jako zmienną `COINGLASS_API_KEY`; bez klucza status MISSING_API_KEY.

## Structure Intelligence, Manual Pad, strefy, biblioteka DB (PMW-UPD-07)
- Instrukcja: `docs/STRUCTURE_INTELLIGENCE_PL.md`, launcher `26_STRUCTURE_INTELLIGENCE.bat`, panel: Modele i trening → Structure Intelligence (`#/struktura`),
  Wykresy → Scalping MTF (karta „Struktura, formacje, świece i MITP”), Setupy → Pozycje i ryzyko → „Manual Trade Pad”.
- Holdout tylko przez `structure-intelligence evaluate-holdout` (jednorazowo). Wybór SHADOW ręcznie; nigdy wykonanie automatyczne.
- Manual Pad: plan → intencja → wykonanie przez wspólny gateway, zgodnie z trybem (PAPER = symulacja, AUTO = potwierdzony rachunek).

## Neutralizacja, operatory SEW, kinematyka Bid/Ask (PMW-UPD-08)
- Instrukcja: `docs/NEUTRALIZATION_SEW_NEWTONIAN_PL.md`, launcher `26_STRUCTURE_INTELLIGENCE.bat` (10–14), panel Structure Intelligence.
- Eksport ticków wykonuje działający bot (job `tick_export`); bez ticków etap kontekstu kwotowań ma BLOCKED_NO_TICK_HISTORY.

## Diagnostyka
- `02_DIAGNOSTYKA.bat` (MT5).
- Dane i diagnostyka: ticki (ACD, kinematyka), repaint, strefy, archiwum prognoz, źródła i licencje.
- Diagnostyka systemu – jak w 1.13.

## Wykonanie zleceń (1.24: Execution Lock wycofany)
- Brak osobnej blokady i frazy. Wysyłkę kontrolują: tryb (SIGNALS / PAPER / AUTO DEMO / AUTO LIVE z potwierdzeniem rachunku), STOP nowych
  wejść, limity ryzyka, aktualne notowania i warunki brokera. Otwarte pozycje są prowadzone także przy STOP.
- Tryb zmienia tylko przycisk „Wykonanie” (`POST /api/v1/mode`); zapis ustawień nie przełącza trybu.
- SCALPING / HEDGING w AUTO LIVE: nowe plany tylko po zaliczonej walidacji strategii na Twojej historii (`30_SH_WALIDACJA.bat`).

## Odzyskanie po awarii
- **Strefy S/D:**
  - źródłem prawdy jest SQLite;
  - przy starcie snapshot `data/lab/zones/zones_<aktywo>.json` (lub `.bak`, gdy główny jest uszkodzony) uzupełnia brakujące wiersze bez duplikatów;
  - zdarzenie widać w Dane i diagnostyka.
- **Nieudany trening:** status FAILED z błędem. Analiza bieżąca działa dalej.
- **Uszkodzony artefakt:** suma kontrolna albo inne aktywo lub schemat → odrzucony z powodem. Usuń katalog z `data/lab/models/<aktywo>/`.

## Powrót do poprzedniej wersji
Rozpakuj `PepeMarketWizard_KLIENT_1_13_0.zip` do osobnego folderu.
- Konfiguracja v11 zawiera nowe pola, których wersja 1.13 nie zna. Program przy migracji sam zapisał kopię `data/config.v10.bak.json`: przed powrotem skopiuj ją jako `data/config.json`.
- Tabele `lab_*` (migracja 0014) są ignorowane przez 1.13.

## Testy
`python tools/run_tests.py`; dla modułu prognoz ustaw `MQ_CANDLES_PYTHON`.
