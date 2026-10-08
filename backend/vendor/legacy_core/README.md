# MasterQUO M04N → M04/M11/M14/M15 | Macro Guard 1.0.0

**Status:** CANDIDATE / PENDING APPROVAL, referencyjna integracja tylko do odczytu. To NIE jest system autoryzacji handlu ani dowód skuteczności strategii.

## Co działa

- **M04N 1.1.0:** ciągły niezależny kolektor Fed/BLS, BLS ICS, Forex Factory + Metals Mine (tygodniowe JSON), GDELT, opcjonalny FRED. Wersja M04N 1.1.0 jest zachowana bajtowo — nie zmieniamy parserów.
- **M04:** oryginalny `calendar_context` interpretuje ważność/okno czasowe znanych wydarzeń CPI/NFP/Fed. `HIGH/EXTREME` w oknie → `macro_gate=BLOCKED`. `PARTIAL` nigdy nie daje globalnego `PASS`.
- **M11:** oryginalny silnik `evaluate` może zostać użyty tylko z prawdziwym, zgodnym czasowo i identyfikatorem `analysis_id` pełnym wejściem `--risk-input`. Bez takiego wejścia `risk_gate=BLOCKED`. Wynik M11 nie odblokowuje makro ani wykonania.
- **M14:** weryfikacja realnego, istniejącego wyniku M14 zawartego w eksporcie M15. Weryfikowana jest jego integralność, `analysis_id`, `as_of`, blokady wykonania i aktualność MT5. Żaden sygnał nie jest generowany przez newsy.
- **M15:** czytelny osobny monitor makro, ostatnia techniczna decyzja M14, nałożona decyzja `WAIT/NO_TRADE`, wydarzenia i ostrzeżenia, stany źródeł. Wysyłka Telegram **wyłącznie po jawnej fladze** i tylko informacji o ryzyku makro; identyfikatory zdarzeń zapisywane w SQLite i nie są ponownie wysyłane automatycznie po niepewnym rezultacie.

## Najprostsze uruchomienie na Windows

1. Uruchom i zaloguj się do MT5 na koncie **DEMO**. Uruchom `py -3 -m pip install MetaTrader5 numpy tzdata` (w niektórych Python/Tkinter potrzebna osobna instalacja Tk).
2. Rozpakuj ZIP do osobnego folderu.
3. Dwukrotnie kliknij **`START_ALL_MT5_MACRO_READONLY.bat`**. Uruchomi cztery okna: kolektor M04N, monitor MT5 MVP/SMC/Scalping/AUTO, Macro Guard, Macro Viewer.
4. W razie potrzeby podaj dokładny symbol brokera przy ręcznym uruchomieniu:

```powershell
py -3 macro_sources\M04N_ENGINE.py --config macro_sources\M04N_CONFIG.json --runtime runtime\M04N
py -3 RUN_MT5_OPERATIONAL_PROFILES_READONLY.py --mode AUTO --symbol XAUUSDm
py -3 M04N_MACRO_GUARD.py
py -3 M04N_MACRO_VIEWER.py
```

**DXY H1** opcjonalnie dostępny w runnerze MT5. Zmienna FRED_API_KEY opcjonalna dla FRED. Nie wymaga klucza OpenAI.

## Pliki i opóźnienia

- `runtime/M04N/M04N_INTELLIGENCE.json` i `M04N_M04_CONTEXT_BRIDGE.json` — nadpisywane atomowo przez kolektor.
- `runtime/M15/M15_MONITOR_SNAPSHOT.json` — wytwarzany przez poprzedni monitor MT5/M10A/M14/M15 (zachowany bez zmian).
- `runtime/M04N_GUARDED_MONITOR.json` — nowy raport; zawiera `macro_gate`, `m04_calendar_context`, `m11_risk_gate`, `m14_original_decision`, `guarded_display_decision`, źródła i ostrzeżenia.
- `runtime/M04N_GUARD_ALERTS.sqlite` — deduplikacja i historia prób alertów makro.
- Feed M04N musi być nie starszy niż 900 s, monitor M15 maks. 15 s; nowy podgląd wymaga 12 s świeżości wyliczonego raportu.

## Granice bezpieczeństwa

- Bazowy M15 pozostaje **monitorowaniem technicznym**. Makro jest nakładane w **nowym panelu M04N_MACRO_VIEWER** i w JSON Macro Guard. Poprzedniego podglądu nie należy traktować jako sygnału zatwierdzonego przez makro. Włączenie starej flagi `--telegram-send` w poprzednim runnerze omija nowe ostrzeżenia makro — **nie włączaj jej**.
- Klasyfikator wiadomości jest heurystyczny. Nagłówki nie stanowią prawdziwych przesłanek kierunkowych. Dwa kalendarze Fair Economy są źródłami skorelowanymi, a zakres wydarzeń jest **niepełny** (brak pełnej certyfikacji FOMC/BEA/geopolityki). PUSTY KALENDARZ ≠ BRAK RYZYKA.
- `PENDING` = brak pewnego potwierdzenia bezpieczeństwa, nie zgoda na wejście; czytelny sygnał LONG/SHORT nie jest w tej nakładce prezentowany jako gotowy, dopóki bramka makro nie daje pełnej pewności (a obecna częściowa nie daje). `BLOCKED` = aktywny HIGH/EXTREME lub dane niewiarygodne.
- Bez rzeczywistego `--risk-input` M11 nie otrzymuje danych o kapitale, zleceniach, prowizji i slippage; dlatego zachowuje `BLOCKED` i NIE wykonuje modelowego lot sizingu. MT5 Zero nie oznacza zerowych rzeczywistych kosztów.
- To jest **sidecar fail-closed**, nie autorytatywny pre-order firewall. Nie modyfikuje silników ani procesu M14 przed jego uruchomieniem. Pełna produkcyjna integracja z pojedynczą bramką wykonania wymaga osobnego połączenia bezpośrednio przed wysłaniem zlecenia, którego tutaj **nie ma**.
- Żaden plik paczki nie wysyła zleceń do brokera. Brak screenshotów/OCR. Testy offline nie zastępują rzeczywistego Windows MT5 DEMO, live feeds i testów alertów Telegram.

## Telegram wyłącznie o ryzyku (opcjonalnie)

Nigdy nie uruchamiaj Telegrama z gotowymi sekretami w paczce. Ustaw w swojej sesji środowiskowej `TELEGRAM_BOT_TOKEN` oraz `TELEGRAM_CHAT_ID` i uruchom ręcznie:

```powershell
py -3 M04N_MACRO_GUARD.py --telegram-send
```

Pierwszy odczyt jest tylko stanem bazowym. Późniejszy nowy alert posiada ID. Próba jest rejestrowana **przed wysyłką**, a odpowiedź niepewna jest zapisywana jako UNKNOWN, bez automatycznego powtórzenia. Nie jest to gwarancja dostarczenia dokładnie raz.

## Testy

```powershell
py -3 -m unittest -q M04N_MACRO_GUARD_TESTS
cd macro_sources
py -3 -m unittest -q M04N_TESTS M04N_FAIR_ECONOMY_TESTS M04N_M04_CONTRACT_TESTS
```

Szybka weryfikacja 287 testów: `py -3 RUN_MACRO_GUARD_ALL_TESTS.py`. Opcjonalna pełna regresja poprzednich silników: `py -3 RUN_MACRO_GUARD_ALL_TESTS.py --full` (może trwać dłużej). Więcej: `M04N_MACRO_AUDIT.md` i `M04N_MACRO_INTEGRATION_CONTRACT.md`.
