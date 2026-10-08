# MasterQUO M06H v1.0.0 — Historical Macro Impact & Strategy Validation

**Status:** CANDIDATE / PENDING APPROVAL · `schema_version=2.0.0` · READ-ONLY · MT5 PRIMARY · ZERO ACCOUNT COSTS **NOT ASSUMED ZERO**.

M06H jest niezależnym, uruchamialnym modułem badawczym. Nie nadpisuje istniejącego M06 ani silników M01–M16. Używa **zachowanego bez zmian** `vendor/M06_REFERENCE_ENGINE.py` do symulacji transakcji, gdy dostarczysz kompletne i chronologiczne dane Bid/Ask oraz historyczny dziennik sygnałów.

## Co naprawdę robi

1. Eksportuje **zamknięte świece M1** bezpośrednio z zainstalowanego MT5 (`M06H_EXPORT_MT5_READONLY.py`, bez `order_send`).
2. Tworzy archiwum kolejnych odczytów M04N (Fed/BLS/Forex Factory/Metals Mine) z **rzeczywistym czasem zapisania**. Łańcuch SHA-256 wykrywa przypadkową zmianę archiwum, ale **nie jest uwierzytelnionym stemplem czasowym ani ochroną przed osobą mogącą przeliczyć cały plik**.
3. Wydobywa wydarzenia kalendarzowe HIGH/EXTREME. Scala duplikaty zgodne co do godziny i tematu, nie liczy obu portali Fair Economy jako niezależnych źródeł; niepewne korekty terminu odrzuca.
4. Mierzy opisową, bezwzględną i kierunkową zmianę zamknięcia świecy XAUUSD po 5/15/60 minutach, według zamrożonej konfiguracji. Odrzuca brakujące bary, niezakończone świece, przecięte granice foldów. Przed publikacją bierze ostatnią dostępną kompletną świecę M1 **bez świecy zawierającej samą publikację**.
5. Dopasowuje opisowe kontrole z tą samą godziną i minutą UTC w innym dniu *w tym samym foldzie*, poza oknem innych wydarzeń. Dodatnia różnica nie dowodzi przyczynowości, poprawy skuteczności ani zysków.
6. Opcjonalnie: używa oryginalnego M06 na **prawdziwym packet M06**: `signals[]`, `ticks[]` z Bid/Ask, `account` z prowizją, poślizgiem i konwersją, zatwierdzone foldy, `trial_ledger`; porównuje **ten sam zestaw sygnałów** przed i po odrzuceniu wejść w znanym w chwili decyzji oknie makro. Raportuje według strategii i folda.

> **Brak historycznych sygnałów/ticków → PnL `NOT_RUN`.** Sama historia świec i kalendarz nie umożliwiają uczciwego backtestu wejść M07/M10A/M14. Wygenerowanie historii sygnałów wymaga osobnego odtwarzacza zamrożonych strategii z czasem dostępności informacji. Nigdy nie rekonstruować sygnałów po fakcie na podstawie świec przyszłych.

## Start Windows 10/11

1. Uruchom **MT5 DEMO** i upewnij się, że w Market Watch widoczny jest dokładny symbol brokera (np. `XAUUSD`, `XAUUSDm`).
2. Rozpakuj ZIP do osobnego katalogu. Otwórz PowerShell z tego katalogu.
3. Eksportuj maksymalnie 45 dni M1 na raz (MT5 musi mieć tę historię):

```powershell
py -3 -m pip install MetaTrader5
py -3 M06H_EXPORT_MT5_READONLY.py --symbol XAUUSD --from-utc 2025-07-01T00:00:00Z --to-utc 2025-08-01T00:00:00Z --output data\XAUUSD_2025_07_M1.csv
```

4. Opcjonalnie eksportuj historyczne ticki Bid/Ask, np. jeden dzień (do 7 dni na plik; strumieniowo i z limitem wielkości). Ticków nie używa się do opisowego event-study, ale są niezbędne do symulacji kosztów i wykonania sygnałów:

```powershell
py -3 M06H_EXPORT_MT5_TICKS_READONLY.py --symbol XAUUSD --from-utc 2025-07-01T00:00:00Z --to-utc 2025-07-02T00:00:00Z --output data\XAUUSD_2025_07_01_TICKS.csv
```

Plik ticków jest eksportem źródłowym, **nie gotowym packetem M06**. Zbudowanie pakietu wymaga punktowego dziennika sygnałów, statusu kontroli M01/M02 oraz zweryfikowanych parametrów rachunku.

5. Uruchom M04N i rozpocznij **archiwizowanie od chwili uruchomienia** (ścieżka do aktualnego raportu zależy od miejsca instalacji poprzedniej paczki):

```powershell
py -3 M06H_ARCHIVE_WATCH.py --input "C:\MasterQUO\runtime\M04N_INTELLIGENCE.json" --archive "runtime_m06h\M04N_HISTORY.jsonl" --interval 60
```

Uwaga: taka archiwizacja od 2026 roku **nie dostarczy historycznych zdarzeń point-in-time sprzed uruchomienia procesu**. Do testu okresów wcześniejszych potrzebne jest osobne, rzeczywiście archiwizowane źródło z udokumentowanym czasem pozyskania; `CURATED_HISTORICAL_EVENTS` pozostaje oznaczone jako `USER_SUPPLIED_UNVERIFIED`.

6. Zanim uruchomisz analizę, dostosuj `M06H_RESEARCH_CONFIG.example.json`: dokładny symbol, okresy development/validation/final OOS, poziomy minimalne, stałe okna HIGH 30min przed / 15min po oraz EXTREME 60min przed / 30min po. **Zamroź konfigurację i zapisz hash przed obejrzeniem OOS.** Nie używaj przykładowych dat bez posiadania odpowiadających im świec i zdarzeń.
7. Uruchom analizę na danych spełniających te warunki:

```powershell
py -3 M06H_RESEARCH_ENGINE.py --bars "data\XAUUSD_2025_07_M1.csv" --events "runtime_m06h\M04N_HISTORY.jsonl" --config M06H_RESEARCH_CONFIG.example.json --output-dir runtime_m06h\analysis
```

Wynik: `M06H_VALIDATION_REPORT.json` (pełny raport i wiersze event study) oraz `M06H_REPORT_PL.md` (polski skrót). Jeżeli kalendarz nie sięga podanych dat, otrzymasz **`INSUFFICIENT_DATA`**, nie fałszywą stopę skuteczności.

**Opcjonalnie** dodaj gotowy pakiet M06 (parametry zgodnie z `vendor/M06_INTEGRATION_CONTRACT.md`):

```powershell
py -3 M06H_RESEARCH_ENGINE.py --bars "data\XAUUSD_2025_07_M1.csv" --events "runtime_m06h\M04N_HISTORY.jsonl" --config M06H_RESEARCH_CONFIG.example.json --m06-packet "data\M06_REAL_HISTORICAL_PACKET.json" --output-dir runtime_m06h\with_trades
```

`M06_REAL_HISTORICAL_PACKET.json` **nie jest częścią paczki** i nie może zostać automatycznie wygenerowany z samych świec M1. Musi zawierać istniejące historyczne sygnały wraz z czasem dostępności ich cech, rzeczywiste ticki Bid/Ask i poprawne informacje o rachunku Zero. Foldy muszą odpowiadać konfiguracji M06H 1:1. Syntetyczne `source_id=MT5_SYNTHETIC` są oznaczone w raporcie jako przykład, nie realizm giełdowy.

## DEMO syntetyczne — sprawdzenie działania

```powershell
py -3 M06H_MAKE_SYNTHETIC_DEMO.py
py -3 M06H_RESEARCH_ENGINE.py --bars examples\DEMO_BARS_SYNTHETIC_M1.csv --events examples\DEMO_EVENTS_SYNTHETIC.json --config examples\DEMO_CONFIG_SYNTHETIC.json --m06-packet examples\DEMO_M06_TICKS_SIGNALS_SYNTHETIC.json --output-dir examples\DEMO_OUTPUT
```

Cena, wyniki, daty i sygnały DEMO są **wymyślone do testów**, nie mają związku z rzeczywistym XAUUSD czy historycznymi publikacjami CPI.

Testy: `py -3 -m unittest -q M06H_TESTS` lub `TEST_M06H_OFFLINE.bat`.

## Granice metody

- **Historyczna reakcja ceny ≠ prognoza przyszłej reakcji.** Raport w punktach bazowych `bp` = 0,01% zmiany zamknięcia ceny. Test kontrolny dopasowuje czas dnia, a nie wszystkie zakłócenia i nie ustanawia związku przyczynowego.
- MT5 `copy_rates_range` udostępnia OHLC brokera, nie potwierdza wykonania ceny Close po Bid/Ask. Użytkownik musi sprawdzić UTC, feed brokera, zmiany czasu i kompletność archiwum.
- `actual/forecast` z portali FF/MM są niezweryfikowane, nie liczymy „surprise” ani kierunku przyszłego rynku.
- Wyniki bazowe M06 uwzględniają spread przez ceny Bid/Ask i nie odejmują go drugi raz. Prowizja, swapy, konwersja i slippage muszą być znane; wartości SCENARIO_ONLY nie certyfikują rachunku Zero.
- Okna newsowe są wstępne i zamrożone: nie stosujemy automatycznej optymalizacji na `FINAL_OOS`.
- Brak informacji o wydarzeniu z częściowego kalendarza **nie oznacza zgody na handel**. M04/M11/M14 pozostają nietknięte.
- Kontrole czasowe używają zamkniętych świec. Przejście do statusu LIVE i wykonanie jest zawsze **`BLOCKED`**; skuteczność rynkowa, wymagania regulatorów i test DEMO nadal `NOT_RUN`.
- W M04N kalendarze Forex Factory i Metals Mine mają wspólną rodzinę Fair Economy; ich zgodność nie stanowi niezależnej weryfikacji danych.

## Dokumentacja

`M06H_INTEGRATION_CONTRACT.md` — kontrakty/wyjścia. `M06H_DATA_AUDIT.md` — metodologia, data quality, proces akceptacji. `M06H_TEST_REPORT.md` — testy, zmiany i limity. `M06H_OUTPUT_SCHEMA.json` — schemat JSON. `SHA256SUMS.txt` — integralność plików ZIP. W `vendor/` znajduje się oryginalny M06 — kod niezmieniony.
