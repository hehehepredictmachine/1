# Świece i prognozy 5/15/30 min (gold_candles) – integracja z MasterQUO 1.11

**Tryb:** wyłącznie SHADOW (obserwacja).
- `forecast.mode = SHADOW`, `ml_execution = false`, `module_order_permission = false`. Konfiguracja nie przyjmuje innych wartości.
- Prognoza nigdy nie daje zgody na zlecenie. Execution Lock modułu zawsze ma stan `BLOCKED`.
- Maszyna stanów strategii v2 kończy najwyżej na `RESEARCH_SETUP_COMPLETE`.

## Jak płyną dane

```
MT5 (sesja bota) ─► MarketBridge: zamknięte M5/M30 XAUUSD-, czas serwera → UTC (zmierzony offset)
      │
      ├─► ForecastService (proces bota, bez pandas)
      │     ├─ po nowej zamkniętej M5: JSON ─► proces roboczy .venv_candles (gold_candles_runtime.worker)
      │     │                                   ├─ gold_candles.analysis.analyze()  (moduł referencyjny, bez zmian)
      │     │                                   └─ model z rejestru (wczytany raz, cache: run_id + checksum)
      │     ├─ maszyna stanów Double Retest v2 (flagi formacji z tego samego modułu)
      │     ├─ forecast_shadow: prognoza zapisana PRZED wynikiem, oceniona po upływie horyzontu
      │     └─ WS „forecast” + GET /api/v1/forecast ─► monitor: Wykresy bota → „Świece i prognozy”
      │
      └─► export-candles (osobne polecenie, własne połączenie) ─► data/forecast/history/<cutoff>/
                                                                     ├─ 12_TRENING ─► data/forecast/runs/<run_id>/
                                                                     └─ registry.json (aktywny model, historia, rollback)
```

**Zasady przepływu danych:**
- Proces roboczy nie otwiera MT5. Bot nie wywołuje `initialize()` ani `shutdown()` dla analityki.
- Referencyjne `gold_candles.mt5_reader.read_mt5()` (initialize + shutdown przy każdym odczycie) **nie jest używane** przez bota.
- Trening i inference używają tej samej konwencji czasu (czas serwera przeliczany na UTC przez bota) oraz tego samego źródła M30 (`BROKER_M30`).

**Środowisko:**
- Moduł przypina numpy 2.3.5, pandas 2.2.3 i scikit-learn 1.8.0. Bot ma numpy 2.5.3 i scikit-learn 1.9.1.
- Dlatego moduł działa w osobnym `.venv_candles`, a środowisko bota nie jest zmieniane.

## Polecenia i launchery (Windows)

| Plik | Działanie |
|---|---|
| `10_PROGNOZY_INSTALUJ.bat` | tworzy `.venv_candles` (pakiety z hashami, `requirements/requirements-candles-win.txt`) i uruchamia testy modułu oraz integracji (dane syntetyczne) |
| `11_EKSPORT_HISTORII_XAUUSD.bat [miesiące]` | `python -m masterquo export-candles --months 12`: zamknięte M5/M30 `XAUUSD-`, cutoff zamrożony przed pierwszym odczytem, porcje miesięczne z checkpointami, `source_metadata.json` (tick_size i specyfikacja z MT5), `DATA_QUALITY_REPORT.json` (luki, duplikaty, rewizje, kompletność M30, dni, warmup) |
| `12_TRENING_MODELI_XAUUSD.bat` | `gold_candles_runtime.plan_train --latest`: zamrożony `TRAINING_PLAN.json` (wspólne granice UTC 60/20/20, embargo 30 min), trening 5/15/30, raport i rejestr; tick size i ścieżki odczytywane automatycznie |
| `13_WALIDACJA_MODELI_XAUUSD.bat` | checksum, zgodność kontraktu z obecnym kodem, odczyt przez ścieżkę bota, tabela jakości |
| `14_ROLLBACK_MODELU_PROGNOZ.bat [BRAK]` | poprzedni zgodny model albo brak modelu (NO_MODEL) |
| `15_START_PROGNOZ_SHADOW.bat` | sprawdza środowisko i rejestr, uruchamia monitor (analityka SHADOW jest częścią zwykłego startu) |

## Trening – co dokładnie robi `plan_train`

**Dlaczego nie `gold_candles.model.train()` bez zmian:**
- Referencyjna funkcja dobiera granice osobno dla każdego horyzontu, według liczby wierszy.
- Przy każdym wywołaniu ocenia końcowy holdout. Wielokrotne uruchamianie pozwalałoby wybierać model po holdoucie.

**Co robi `plan_train` – pliki referencyjne zostają nietknięte, zmiana jest w osobnym pliku runtime:**
1. Zapisuje `TRAINING_PLAN.json` **przed** treningiem i wiąże go z hashem danych. Plan innego zbioru jest odrzucany.
2. Ustala jedne granice dla 5/15/30: 60/20/20 rozpiętości czasu kompletnych wierszy cech, cięte o 00:00 UTC.
   - Purge według końca etykiety: fit kończy się przed `kalibracja − 30 min`, kalibracja przed `holdout − 30 min`.
3. Używa modeli i hiperparametrów referencyjnych, bez strojenia:
   - regresja logistyczna;
   - osobny kalibrator na okresie kalibracyjnym;
   - GBR kwantylowy q10/q50/q90 znormalizowanej zmiany ceny.
4. Porównania są zadeklarowane w planie przed treningiem:
   - baseline częstości klas;
   - ten sam model **bez flag formacji**, czyli przyrostowa wartość formacji.
5. Holdout jest oceniany raz. Raport zawiera:
   - Brier, log loss, balanced accuracy, recall i ECE dla każdej klasy;
   - krzywe niezawodności;
   - pokrycie q10–q90 i MAE mediany;
   - przedziały 95% z bootstrapu bloków dni (nakładające się prognozy są zależne);
   - podział na sesje.
6. Sprawdza przenośny JSON (bez pickle) względem scikit-learn. Potem model jest wczytywany loaderem referencyjnym i liczony przez `forecast()`, tak jak robi to bot. Wynik zapisuje w `runtime_check`.
7. Prowadzi rejestr:
   - zawartość wpisu: run_id, commit/fingerprint kodu, hash danych, contract_hash, symbol, tick_size, źródło M30, cechy, próg etykiet, horyzonty, wersje bibliotek, knowledge_cutoff, czas treningu, statusy, checksum artefaktu;
   - aktywacja atomowa;
   - aktywny może być tylko model z danych `REAL_USER_DATA`, z wszystkimi trzema horyzontami, zgodny z bieżącym kodem.
8. Długie zadanie można wznowić: każdy horyzont ma checkpoint. Log `run_log.jsonl` zapisuje czas, krok, szczytowe zużycie pamięci, polecenie i interpreter.

**Statusy horyzontu:**
- `INSUFFICIENT_DATA` – z brakującą liczbą wierszy lub klas;
- `REJECTED` – Brier lub log loss nie lepszy od baseline;
- `SHADOW_UNVALIDATED` – lepszy od baseline, ale np. holdout krótszy niż 30 dni albo ECE > 0,10;
- `SHADOW_VALIDATED` – kryteria jakości **ceny** spełnione.

**Status całości:**
- `TRAINED_SHADOW` – wszystkie horyzonty zwalidowane;
- `PARTIAL_VALIDATION`, `SHADOW_UNVALIDATED`, `REJECTED` albo `INSUFFICIENT_DATA` – w pozostałych przypadkach.

Żaden z tych statusów nie dotyczy rentowności strategii: `STRATEGY_BACKTEST_NOT_AVAILABLE`.

## Monitor – Wykresy bota → „Świece i prognozy”

**Co pokazuje sekcja:**
- zamknięte M5/M30, ich czas i wiek;
- formacje (rodzina, hipoteza morfologii);
- prognozy 5/15/30: P(spadek/płasko/wzrost) i q10/q50/q90 close, ze statusem modelu każdego horyzontu i kontrolą przerwy rynku;
- aktywny run: zakres treningu, wiedza do, status;
- stan eksportu historii, proces analityki (wersje, czas analizy) i bieżącą ocenę SHADOW;
- checklistę setupu v2 dla BUY i SELL: L, strefa, epizody, reclaim, retest, następne zdarzenie, unieważnienie, ostatnie zakończone.

**Statusy z powodami:**

| Status | Znaczenie |
|---|---|
| NO_CANDLE_ENV | brak `.venv_candles` |
| NO_MODEL | brak aktywnego modelu (np. trening nie wykonany) |
| WARMUP | za mało danych do cech |
| STALE_DATA | dane nieaktualne |
| CONTRACT_MISMATCH | model niezgodny z kodem, symbolem lub tick size |
| MODEL_FROM_FUTURE | model z wiedzą późniejszą niż analizowany snapshot |
| FORECAST_UNAVAILABLE | błąd procesu; ochrona pozycji działa bez zmian |
| SHADOW | prognoza obserwacyjna |

**Kontrola przerwy rynku:** moduł referencyjny nie zna sesji brokera.
- Horyzont obejmujący weekend (pt 21:00 – nd 22:00 UTC) dostaje `BLOCKED_SESSION_BREAK`.
- Pozostałe horyzonty mają `NOT_VERIFIED_BROKER_SESSIONS`; dzienne przerwy i święta są nieznane.

## Czego to nie robi

- Nie wysyła zleceń, nie zmienia strategii S01–S12, ryzyka, SL/TP ani zarządzania otwartymi pozycjami.
- P(UP) nie jest P(TP przed SL), win rate ani EV transakcji.
- Bez historii tickowej nie ma tickowego backtestu SL/TP, poślizgu ani częściowych realizacji.
- Nie ma modelu wyniku transakcji (Trade Outcome Forecast). Wymaga on osobnych etykiet z tickowego replayu.
- Nie ma LSTM/TCN/Transformer. Zaimplementowano tylko referencyjny baseline.

## Rollback

| Co cofnąć | Jak |
|---|---|
| model | `14_ROLLBACK_MODELU_PROGNOZ.bat` (poprzedni zgodny) albo `… BRAK` (NO_MODEL). Zmiana działa od następnej zamkniętej M5 |
| funkcję | w `data\config.json`: `"forecast": {"enabled": false}`; monitor pokaże DISABLED |
| wersję | 1.11 → 1.10.1: migracja `0011` tylko dodaje tabelę `forecast_shadow`; sekcja `forecast` w `config.json` musi zostać usunięta przed uruchomieniem 1.10.1 (stare wersje odrzucają nieznane pola); `.venv_candles` i `data\forecast\` można zostawić albo usunąć |
