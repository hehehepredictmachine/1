# RUNBOOK – PepeMarketWizard 1.14

## Uruchomienie
1. Rozpakuj `PepeMarketWizard_KLIENT_1_14_0.zip`. Dane z wcześniejszej wersji (`data/`) zostają.
   - Konfiguracja migruje się sama do wersji 11.
   - XAUUSD dostaje symbol, który był wpisany wcześniej (domyślnie `XAUUSD-`).
   - **Execution Lock = LOCKED.**
2. Uruchom `03_START_MASTERQUO.bat` (MT5 musi być uruchomiony i zalogowany).
3. Pulpit pokazuje:
   - aktywo i symbol brokera;
   - wiek notowania, reżim i sesję;
   - kartę scenariusza;
   - aktywność modelu. Bez artefaktu: „Sieć nieaktywna”.

## Aktywa
- Ustawienia → Aktywa:
  - XAUUSD jest wstępnie przypisane do Twojego symbolu, a metadane są sprawdzane przy połączeniu;
  - konflikt metadanych (np. inny kontrakt) blokuje tylko to aktywo.
- BTC: przycisk „Szukaj kandydatów”, potem „Potwierdź” przy właściwym symbolu. Program sam niczego nie wybiera.
- Przełącznik XAUUSD/BTC jest w górnym pasku. Po przełączeniu bridge wczytuje historię nowego symbolu, a panel czeka na nowe dane i nie pokazuje starych.

## Trening i badania
- Modele i trening → wybierz rodziny → „Uruchom badanie dla <aktywo>”.
  - Zadanie ma postęp, log i przycisk Anuluj.
  - Wynik jest zapisywany atomowo w `data/lab/studies/`.
- Artefakt powstaje:
  - automatycznie – tylko gdy kandydat przejdzie walidację;
  - albo z ręcznym wyborem rodziny – wtedy ma rolę „badawczy”, a na danych syntetycznych „techniczny”.
- Badania i walidacja: werdykt, foldy, kontrole, rejestr prób, holdout, macierz M01–M42.

## Diagnostyka
- `02_DIAGNOSTYKA.bat` (MT5).
- Dane i diagnostyka: ticki (ACD, kinematyka), repaint, strefy, archiwum prognoz, źródła i licencje.
- Diagnostyka systemu – jak w 1.13.

## Execution Lock
- Domyślnie LOCKED. Żadna ścieżka nie wysyła `order_send`, a pozycje nie są modyfikowane (odczyt i rozliczenie działają).
- Odblokowanie: Ustawienia → Execution Lock → wpisz frazę `ODBLOKUJ WYKONANIE ZLECEN`. Twoja decyzja – testy programu tego nie robią.

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
