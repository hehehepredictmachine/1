# MasterQUO Candle Reader & Forecast v2

Pakiet zawiera pełny audyt promptu, samodzielny poprawiony prompt v2 i działający moduł Python do analizy świec XAUUSD. Rozpoznaje 23 flagi formacji, potrafi czytać CSV lub terminal MT5 i umożliwia trening prognoz na 5, 15 i 30 minut.

**Moduł nie wysyła zleceń. Nie jest zintegrowany z Twoim botem. Nie zawiera modelu wytrenowanego na rzeczywistym rynku.** Bez modelu pokazuje formacje i `NO_TRAINED_MODEL`, z pustymi prawdopodobieństwami. Po treningu wynik pozostaje w trybie badawczym SHADOW, a Execution Lock blokuje zlecenia.

## Pliki do przeczytania

1. `MasterQUO_AUDYT_SCALPING_v2.md` — problemy, priorytety, poprawki i zakres wykonanych testów.
2. `MasterQUO_XAUUSD_EXECUTION_LOCK_v2_PROMPT.md` — cały prompt do Claude Code. Skopiuj treść między POCZĄTEK/KONIEC PROMPTU.
3. `gold_candles/` — kod, który możesz przekazać Claude Code do integracji.
4. `tests/test_candles.py` — 29 testów programu; dane testowe są syntetyczne.
5. `config_strategy_v2_research.json` — jawne wartości startowe strategii. Ten plik jest specyfikacją dla integratora; sam moduł świec nie uruchamia strategii na jego podstawie.

## Uruchomienie na Windows

Wymagany Python 3.12 64-bit. Rozpakuj archiwum do zwykłego folderu. Uruchom `INSTALUJ_WINDOWS.bat`, a następnie `DEMO_WINDOWS.bat`.

Alternatywnie w PowerShell, w folderze paczki:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m gold_candles demo --output demo_analysis.json
```

Demo jest oznaczone SYNTHETIC_DEMO i korzysta z wymyślonych cen tylko do sprawdzenia programu. Nie jest backtestem i nie zawiera bieżącego sygnału.

## Odczyt Twojego terminala MT5

Otwórz i zaloguj swój terminal MT5. Moduł używa istniejącej sesji; nie zapisuje haseł. Domyślny symbol to `XAUUSD-`. Jeśli nie istnieje lub terminal nie potwierdza bazowej waluty XAU i kwotowania USD, moduł zgłasza blokadę.

```powershell
.\.venv\Scripts\python.exe -m gold_candles mt5-once --symbol XAUUSD- --output mt5_analysis.json
.\.venv\Scripts\python.exe -m gold_candles mt5-watch --symbol XAUUSD-
```

Monitoring odczytuje dane co sekundę, ale nowy raport publikuje przy nowej zamkniętej świecy. Zmiana odczytanego zamkniętego OHLC powoduje blokadę i zakończenie procesu; zbadaj źródło rewizji przed ponownym uruchomieniem. Ctrl+C kończy monitoring.

Czytane są zamknięte M5 i M30. SDK Python zwraca czas UTC; moduł nie dodaje offsetu brokera. Prawdopodobieństwa bez modelu pozostają null.

## Eksport rzeczywistej historii

```powershell
.\.venv\Scripts\python.exe -m gold_candles export-mt5 --symbol XAUUSD- --count 30000 --output-dir dane_xauusd
```

Otrzymasz CSV M5, CSV M30 i `source_metadata.json`. Terminal musi mieć dostępną historię; ograniczenie „Max. bars in chart” może zmniejszyć wynik. Sprawdź liczebność i zakres dat. Eksport liczby barów nie jest gwarancją kompletności.

W `source_metadata.json` odczytaj rzeczywisty tick_size. W poleceniach treningu użyj tego tick size. **0.01 w przykładzie poniżej jest tylko przykładem**; zgodność modelu z rzeczywistą specyfikacją jest wymagana.

## Trening offline na danych brokera

```powershell
.\.venv\Scripts\python.exe -m gold_candles train --m5 dane_xauusd\XAUUSD_M5.csv --m30 dane_xauusd\XAUUSD_M30.csv --symbol XAUUSD- --tick-size 0.01 --output-dir model_xauusd
```

Program zapisze `forecast_model.json` i `forecast_validation.json`. Model jest przechowywany w JSON jako współczynniki i drzewa numeryczne; nie wymaga ładowania pickle. Zapisany kontrakt uwzględnia konfigurację, kolejność cech i hashe kodu. Zmiana kodu lub kontraktu wymaga nowego treningu.

Techniczne minimum to 1500 kompletnych wierszy cech oraz minimum 600 train/200 calibration/250 holdout z odpowiednimi klasami. To dolna granica wykonania programu, nie wystarczająca próba do wdrożenia tradingowego. Zbieraj znacznie dłuższą historię obejmującą różne sesje i reżimy.

Pola `probability_quality_candidate` opisują tylko podstawowe kryteria jakości modelu ceny. Nawet true nie odblokowuje strategii, nie zastępuje backtestu P&L i nie dowodzi dodatniej wartości transakcji.

Trening dzieli dane chronologicznie na train, kalibrację i holdout, usuwa etykiety przenikające granice i stosuje 30-minutowe embargo dla prognozy 30 minut. To embargo nie jest automatycznie właściwe dla symulatora całego setupu. Nie wykorzystuj wielokrotnie końcowego holdoutu do strojenia.

## Prognoza z wytrenowanym modelem

```powershell
.\.venv\Scripts\python.exe -m gold_candles mt5-once --symbol XAUUSD- --model model_xauusd\forecast_model.json --output prognoza_xauusd.json
.\.venv\Scripts\python.exe -m gold_candles mt5-watch --symbol XAUUSD- --model model_xauusd\forecast_model.json
```

Prognozy odnoszą się do przyszłego close: UP ponad +0.20 ATR, DOWN poniżej -0.20 ATR, FLAT w tym paśmie. q10/q50/q90 to estymowane kwantyle ceny, z empiryczną oceną pokrycia w raporcie. Nie oznaczają prawdopodobieństwa TP przed SL ani gwarantowanego zakresu ruchu.

Model wymaga zgodnego symbolu, tick size, cech i źródła M30. Gdy trenowałeś bez CSV M30, moduł sam agreguje pełne M30 z M5; takiego modelu nie można użyć z bezpośrednim kontekstem BROKER_M30 bez ponownego treningu. Do MT5 używaj obu wyeksportowanych CSV.

W przyszłym horyzoncie muszą występować ciągłe świece M5. Moduł nie integruje jeszcze kalendarza sesji brokera; prognozę obejmującą planowaną przerwę traktuj jako niedopuszczalną do wykonania. Pełny silnik strategii ma osobno kontrolować tę sytuację.

## Własny CSV i odtwarzanie historyczne

Wymagane kolumny:

```csv
time_open_utc,open,high,low,close,tick_volume,symbol
2026-01-05T08:00:00Z,4140.0,4141.0,4139.5,4140.4,100,XAUUSD-
```

Wiersz jest hipotetyczny. `tick_volume` i `symbol` są opcjonalne, ale gdy symbol występuje, musi zgadzać się z konfiguracją. Cena ma być zgodna z feedem źródłowym; sam nagłówek CSV nie potwierdza pochodzenia danych.

```powershell
.\.venv\Scripts\python.exe -m gold_candles analyze --m5 twoje_M5.csv --m30 twoje_M30.csv --symbol XAUUSD- --tick-size 0.01 --mode REPLAY --output analiza_csv.json
```

Do odtworzenia konkretnej chwili podaj `--as-of 2026-01-05T12:00:00Z` i CSV zawierający wyłącznie otwarcia do tego czasu. Otwarte świece zostaną pominięte; wiersze o przyszłym otwarciu są błędem. Replay ma odrębny status i nie jest bieżącym sygnałem.

## Weryfikacja

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

W środowisku autora 29 testów przeszło poprawnie. Python 3.12.14, NumPy 2.3.5, pandas 2.2.3, scikit-learn 1.8.0. SDK MT5 sprawdzono przez stub; rzeczywistego terminala Windows, modelu na danych brokera i rentowności strategii nie testowano.

Test eksportu modeli porównuje wynik przenośnej implementacji JSON z wynikiem scikit-learn. Dane używane do testowania prognoz są jawnie SYNTHETIC_TEST i nie nadają modelowi statusu rynkowego PASSED.

## Integracja z istniejącym botem

Przekaż Claude Code cały folder `gold_candles`, testy, README i prompt v2. Główne wywołanie:

```python
from gold_candles.mt5_reader import read_mt5
from gold_candles.analysis import analyze
from gold_candles.model import load_model

m5, m30, config, quote, now = read_mt5("XAUUSD-")
report = analyze(m5, m30, config, model=None, as_of=now, mode="LIVE", quote=quote)
```

Po własnym treningu można przekazać `model=load_model("forecast_model.json")`. Raport nadal nie upoważnia do zlecenia. Silnik MasterQUO musi osobno wdrożyć maszyny stanów setupu/pozycji, prowizje, ryzyko, kalendarz, prawdziwy backtest i uprawnienia wykonania.

