# PMW-SH-1 · Trening, eksport pakietu, uruchomienie, migracja, rollback, blokery

## Panel treningu (Modele i trening → Trening modeli)

| Zakładka | Co robi | Endpoint |
|---|---|---|
| Rejestr modeli | wszystkie 26 komponentów: rola SCALPING/HEDGING, grupa korelacji, status z sondy, gotowość, ostatni trening, blokady. Moduły deterministyczne pokazują „nie wymaga treningu”. Model zdarzenia SH: runy, holdout, promocja, rollback. | `GET /api/v1/training/models` |
| Uruchom | kontrola gotowości (inny trening, MT5, symbol brokera, dysk, środowisko świec, instrument SH, prowizja, poprzedni eksport); start jednego modelu, wybranych albo wszystkich w kolejności zależności; anuluj; wznów | `GET /readiness`, `POST /start {tasks}`, `/cancel`, `/resume` |
| Postęp | rzeczywisty postęp: ukończone zadania planu oraz licznik `[POSTEP] i/n` raportowany przez trener (bez szacowania czasu); stany sukces / błąd / pominięte / anulowane / **UTRACONY PROCES** (stan RUNNING bez żywego procesu); log każdego zadania; raport HTML | `GET /runs/{id}`, `/runs/{id}/log`, `/runs/{id}/report` |
| Historia | lista runów, porównanie dwóch wersji (plan i zadania) | `GET /runs`, `/compare` |
| Eksport / import | pakiet całości albo jednego modelu; import pakietu z weryfikacją sum (run SH dodawany jako kandydat, aktywny model bez zmian) | `POST /export`, `GET /exports/{plik}`, `POST /import` |

Stan treningu jest trwały: `data/training/runs/<run>/state.json` jest zapisywany atomowo, a `RUNNING.lock` zawiera PID.
Trening działa w osobnym procesie, bez zleceń i bez zmiany Execution Lock.

## Pakiet treningowy (ZIP)

Zawartość pakietu:
* `data/`: eksport MT5 (CSV per TF), `source_metadata.json` (pochodzenie, symbol, specyfikacja, koszty, czas),
  `DATA_QUALITY_REPORT.json`;
* `config/`: jedno źródło konfiguracji SH (plus override), profile treningu, instrumentów i scalp;
* `training/`: plan, zadania, raport, logi runu;
* `models/`: rejestry i artefakty;
* `MANIFEST.json`: SHA-256 każdego pliku, wersja kodu (APP_VERSION, commit git, wersje bibliotek), schematy cech, etykieta,
  preprocessing, podział danych, ziarno, koszty instrumentu, polecenia odtworzenia, lista braków;
* `README_REPRODUKCJA.md`.

Pakiet **nie zawiera** sekretów: pola o nazwach typu secret, token, password lub api_key są usuwane, a pliki secrets, `.env`
i `config.json` są pomijane (test `test_package_roundtrip_no_secrets`). Brak historii jest zapisany w manifeście jako
brak; niczego się nie podstawia.

## Uruchomienie

1. `PepeMarketWizard.exe` albo `03_START_MASTERQUO.bat`, a potem w panelu **Setupy → SCALPING / HEDGING**.
2. Domyślnie tryb SIGNALS albo PAPER:
   * SIGNALS: tylko sygnały;
   * PAPER: symulowane wykonania, z poziomami liczonymi od symulowanego fill.
3. AUTO_DEMO dla SH wymaga wszystkich warunków naraz:
   * odblokowanego Execution Lock;
   * rachunku DEMO;
   * trybu PEŁNEGO (model zdarzenia READY po treningu na danych klienta);
   * znanej prowizji.
4. AUTO_LIVE dla SH jest zablokowane.

## Migracja

* Migracja bazy `0023_sh_strategies.sql` jest addytywna (nowe tabele `sh_*`). Kopia bazy powstaje automatycznie przed
  migracją.
* Stare strategie S01–S12, stary menedżer pozycji i ich tabele pozostają bez zmian.
* SH ma własny magic 41082100 i komentarz `SH:`. Ręczna adopcja pozycji SH przez stary menedżer jest odrzucana.

## Rollback

* **Konfiguracja SH**: przycisk „Przywróć poprzednią” albo `POST /api/v1/sh/config/rollback`. Historia wersji jest w
  `data/sh/config_override.json`.
* **Model zdarzenia**: przycisk „Rollback” w rejestrze albo `POST /api/v1/training/rollback {family: "sh:SCALPING"}`. Pliki
  poprzednich runów nie są usuwane.
* **Cała funkcja SH**: tryb SIGNALS albo zamknięcie planów („Zamknij plan”). Usunięcie `self.sh` z `runtime.py` cofa
  integrację; tabele `sh_*` mogą zostać, bo nic innego ich nie czyta.

## Lista blokerów

| # | Bloker | Skutek | Co jest potrzebne |
|---|---|---|---|
| B-DATA | brak historii XAUUSD-/BTC z terminala klienta w tym środowisku | brak walidacji jakości, brak treningu modelu zdarzenia, brak analizy ablacyjnej i korelacji błędów | uruchomić trening na komputerze z MT5 (panel lub `00_TRENING_START.bat`) |
| B-COMM | prowizja XAUUSD-/BTC nieznana (`commission_per_lot_side: null`) | koszt niepełny w setupach i raportach; AUTO zablokowane | odczyt z historii transakcji przy eksporcie albo wpis w konfiguracji SH |
| B-SWAP | swap nieuwzględniony | wynik HEDGING (do 8 h) bez kosztu nocnego | specyfikacja swap symbolu w profilu |
| B-TICKS | brak danych tickowych | replay konserwatywny na M1 | eksport ticków (MT5 `copy_ticks_range`) – niezaimplementowany |
| B-MT5 | brak terminala MT5 w środowisku testowym | test AUTO_DEMO tylko na symulatorze terminala | test na rachunku DEMO klienta |
| B-BTC | parametry BTC szkicowe, instrument wyłączony | brak sygnałów SH dla BTC | kalibracja i walidacja na danych BTC klienta, potem `enabled: true` |
| B-ACC | rachunek netting/exchange | HEDGING zablokowany (widoczny powód) | rachunek typu hedging |
