# Aktualizacja do 1.33.0 i powrót do 1.32.0

## Przed aktualizacją
1. Zatrzymaj bota przyciskiem **STOP → zamknij aplikację** albo `04_STOP_MASTERQUO.bat`. Otwarte pozycje zostają w MT5. Po starcie bot je
   uzgodni (rekonsyliacja), a nowe wejścia nie są składane bez Twojego trybu.
2. Zrób kopię folderu danych:
   * aplikacja Windows (DESKTOP): `%LOCALAPPDATA%\PepeMarketWizard\data` (aplikacja robi też własną kopię w `...\backups` przed migracją);
   * wersja folderowa: `<folder programu>\data`.
3. Sprawdź sumę paczki: `PepeMarketWizard_DESKTOP_1_33_0.zip.sha256` (PowerShell: `Get-FileHash <zip> -Algorithm SHA256`).

## Aktualizacja
**Aplikacja Windows:**
1. Rozpakuj `PepeMarketWizard_DESKTOP_1_33_0.zip` do **nowego** folderu. Ścieżka może zawierać spacje.
2. Uruchom `PepeMarketWizardDesktop.exe`. Aplikacja znajdzie dotychczasowy folder danych.
3. Przy pierwszym starcie:
   * baza dostaje migrację **0025** (nowe tabele, niczego nie usuwa);
   * `config.json` przechodzi na **v13**, a nietknięta kopia 1.32 zostaje jako `data\config.v12.bak.json`.

**Wersja folderowa:** rozpakuj `PepeMarketWizard_1_33_0.zip`, skopiuj swój folder `data` i uruchom `01_INSTALUJ.bat` (nowe pakiety
statsmodels / arch / pandas, sumy SHA-256), a potem `03_START_MASTERQUO.bat`.

**Opcjonalnie:**
* `34_DEEP_INSTALUJ.bat` – środowisko `.venv_deep` dla LSTM / GRU / PPO (bez niego te 3 rodziny mają stan MISSING_DEPENDENCY);
* ustaw symbol DXY brokera w Ustawieniach, żeby zadziałała relacja XAUUSD × DXY.

**Co się nie zmienia:**
* tryb wykonania, STOP, limity, mapowanie symboli, strategie i ich progi;
* wszystkie nowe modele mają rolę OFF albo SHADOW, a `decision.required_models` jest puste – decyzje są takie jak w 1.32.

**Nowe:** Studio (przycisk **Studio** w górnym pasku), `#/dxy`, `#/svp`, `#/decyzje`, sekcja „Rodziny modeli 1.33” w Centrum treningu.

## Sprawdzenie po aktualizacji
* W stopce lub menu widać wersję 1.33.0. Diagnostyka nie pokazuje błędów migracji.
* Ustawienia i diagnostyka → **Koordynator decyzji**: rekordy decyzji pojawiają się po pierwszych cyklach analizy.
* Centrum treningu → Rodziny modeli: 16 wierszy, role OFF/SHADOW.

## Powrót do 1.32.0 (rollback)
1. Zamknij 1.33.0.
2. **Konfiguracja.** 1.32 nie zna sekcji `indicators` / `families` / `decision` i odmówi startu z `config.json` zapisanym przez 1.33.
   * W folderze danych zmień nazwę `config.json` na `config.v13.json` (zachowasz ustawienia 1.33).
   * Skopiuj `config.v12.bak.json` jako `config.json`.
   * Zmiany ustawień zrobione w 1.33 trzeba powtórzyć w 1.32.
   * Alternatywa: przywróć cały folder danych z kopii sprzed aktualizacji.
3. **Baza danych** może zostać. Tabele 1.33 (`decision_records`, `execution_intents`, `risk_reservations`) są przez 1.32 ignorowane
   (sprawdzone: `tools/migration_check.py --old-ref 5e5d82a`, 13/13 PASS, w tym start 1.32.0 na danych po 1.33.0 z przywróconą
   `config.v12.bak.json`).
4. Uruchom 1.32.0 z jej folderu (`PepeMarketWizard_DESKTOP_1_32_0.zip`).
5. Paczki zaimportowane ze Studio i artefakty rodzin modeli (`data\families`, `data\studio_imports.json`) nie przeszkadzają, bo 1.32 ich nie czyta.

Powrót ponownie do 1.33.0: przywróć `config.v13.json` jako `config.json` albo pozwól 1.33 zmigrować plik 1.32 jeszcze raz.
