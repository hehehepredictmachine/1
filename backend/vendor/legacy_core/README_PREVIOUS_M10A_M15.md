# MasterQUO — M01 Audyt + M03E Early + M10 Lifecycle (v1.0.0-CANDIDATE)

**Status:** kandydat badawczy, nie zintegrowany z produkcyjnym botem. MT5 Zero zadeklarowane, **koszty brokera niepotwierdzone**, transakcje automatyczne WYŁĄCZONE.

## Windows — uruchomienie

1. Rozpakuj archiwum. Uruchom i zaloguj się do własnego MetaTrader 5 (rachunek demo do testów).
2. Otwórz PowerShell w folderze paczki i wykonaj:

   ```powershell
   py -3 -m pip install MetaTrader5 numpy
   py -3 RUN_MT5_READONLY_SIGNAL_LIFECYCLE.py --symbol XAUUSD
   ```

   Opcjonalnie `--dxy-symbol <symbol-u-brokera>` albo `--terminal-path "C:\\...\\terminal64.exe"`. Plik `START_READONLY_MT5_M03E_M10.bat` uruchamia te same polecenia (bez instalacji zależności).
3. Odczytaj `runtime/MASTERQUO_M03E_M10_MONITOR.json` (jeśli istnieją ważne dane). To **raport diagnostyczny**, nie sygnał do wykonania. Stan M10 zachowuje się w lokalnej bazie SQLite.
4. Aby badać konkretną strategię, uzupełnij `STRATEGY_PLAN.example.json` o rzeczywiste dowody M02/M03 i reguły zamrożone w M07. Dopiero wtedy uruchom `--strategy-plan NAZWA_PLIKU.json`. Wszelkie placeholdery uniemożliwią EARLY. Nie należy kopiować sztucznych cen ani wymyślać evidence ID.
5. Aby zakończyć monitoring, naciśnij `Ctrl+C`.

## Zasady

- Na starcie pobierana historia do wyliczenia EMA 200 i M03; odczyt BID/ASK odświeżany częściej niż świece. Przez pierwsze sekundy lub przy brakach status może być PENDING.
- D1, H4, H1, M15, M5, M1: zamknięte świece MT5; DXY H1 opcjonalnie.
- Aktualizacje samych kwotowań nie tworzą nowych eventów ani nie przeliczają historycznych setupów; w raporcie widać, kiedy wynik powstał z ostatnich zamkniętych świec.
- Przy stale/fail/disconnect monitor publikuje `NO_TRADE`, `BLOCKED`, null bieżącej kwotacji.
- Dane M03E: pięć CORE; M10: stabilne ID, baza SQLite, TTL/aging. Poziomy entry/SL/TP pozostają nieznane, gdy brak zatwierdzonego planu.
- M14/M11 i zlecenia LIVE są **zawsze zablokowane**. Brak połączenia TradingView nie oznacza utraty źródła głównego MT5.
- Żaden plik nie wymaga API OpenAI, Telegram, haseł ani screenshotów. Program wymaga uruchomienia lokalnie na Windows; nie jest usługą chmurową działającą w tej rozmowie.

## Testy offline

```powershell
py -3 -m pip install numpy
py -3 RUN_ALL_OFFLINE_TESTS.py
```

Testy używają syntetycznego terminala `FakeMT5`, bez logowania i wysyłania zleceń. Wynik PASS nie dowodzi realnych zysków ani gotowości LIVE.

## Pliki

- `M01_AUDIT.py` — konserwatywny audyt M01 tylko do odczytu.
- `M03E_M10_PIPELINE.py` — połączenie M01→M02/M02I→M03E→M09/M14→M10.
- `RUN_MT5_READONLY_SIGNAL_LIFECYCLE.py` — działający proces Windows + JSON monitor.
- `INTEGRATION_TESTS.py` i `RUN_ALL_OFFLINE_TESTS.py` — testy i regresja.
- `STRATEGY_PLAN.example.json` — jawne wymagania CORE i planu strategii.
- `vendor/` — zachowane, niezmienione silniki M01/M02/M02I/M03/M09/M10/M14.
- `INTEGRATION_CONTRACT.md` — szczegółowe wejścia, wyjścia, ograniczenia i bramki.
- `AUDIT_CHANGELOG_TEST_REPORT.md` — zakres weryfikacji i rzeczywiste wyniki.
