# MasterQUO M06R v1.0.0 — Historical Strategy Replay Engine

**STATUS: CANDIDATE / RESEARCH ONLY / PENDING APPROVAL.**

Nowy etap systemu MasterQUO XAUUSD: odtwarza historyczną analizę świeca po świecy na danych eksportowanych z MetaTrader 5, wykorzystując zachowane silniki M02, M02I, M03 i M07/M03E. Oddzielna warstwa naśladuje logikę stanów M10 i sprawdza ceny według zasad M10A. Rejestruje badawcze hipotezy i ich fazy, lecz **nie symuluje realizacji transakcji**.

Nie ma automatycznych zleceń, analizy screenshotów/OCR, prognoz skuteczności, odblokowania wykonania ani automatycznej wysyłki Telegram.

## 1. Pliki

- `M06R_EXPORT_MT5_ALL_TIMEFRAMES.py` — eksport zamkniętych świec **bezpośrednio z zalogowanego terminala MT5** dla D1/H4/H1/M15/M5/M1. Zachowuje oryginalne granice świec brokera. Nie przelicza D1/H4 z M1. Tworzy `MT5_EXPORT_MANIFEST.json` z kontrolą SHA-256 każdego CSV.
- `M06R_HISTORICAL_REPLAY.py` — ścisła walidacja CSV i replay point-in-time, oryginalne M02/M02I/M03, detektor M07, fazy M10A, eksport JSON/JSONL.
- `M06R_MAKE_SYNTHETIC_DEMO.py` — **wymyślone dane edukacyjne**, niewłaściwe do badania wyników rynku.
- `M06H_RESEARCH_ENGINE.py` — zachowana walidacja wydarzeń makro M06H z opcjonalnym overlayem archiwum `--macro-events`.
- `vendor/` — niezmienione referencyjne implementacje M02/M02I/M03/M10/M06/M09/M14. Oryginalne moduły w innych paczkach nie są nadpisywane.
- `M06R_TESTS.py`, `M06R_INTEGRITY_MACRO_TESTS.py` — testy nowego modułu.
- `M06H_TESTS.py`, `M07_M03E_PROFILE_TESTS.py` — testy regresyjne odpowiednich starszych modułów.

## 2. Instalacja Windows

Potrzebny jest Windows, zalogowany i połączony MetaTrader 5 oraz Python. Na komputerze z MT5:

```powershell
py -3 -m pip install MetaTrader5 numpy
```

**Eksport danych z terminala:** przy analizie rocznej zaplanuj odpowiednio długi okres, bo potrzeba min. 230 świec D1 na rozgrzewkę, a terminal może nie przechowywać tylu historycznych świec M1. W razie potrzeby zwiększ `Max. bars in chart` i zapewnij historię u brokera.

```powershell
py -3 M06R_EXPORT_MT5_ALL_TIMEFRAMES.py --symbol XAUUSD --from-utc 2025-06-01T00:00:00Z --to-utc 2026-10-01T00:00:00Z --output-dir data_mt5_six_tf
```

Jeśli instrument ma suffix, np. `XAUUSDm`, użyj dokładnie tej nazwy w eksporcie i replay. Eksport maks. 500 dni/jedno wywołanie i maks. 1 000 000 barów na timeframe. API MT5 ma ograniczenia dostępności historii i rzeczywistej długości świec.

**Odtwarzanie wybranego okna:**

```powershell
py -3 M06R_HISTORICAL_REPLAY.py --bars-dir data_mt5_six_tf --symbol XAUUSD --mode AUTO --step-tf M5 --replay-from-utc 2026-08-01T00:00:00Z --replay-to-utc 2026-09-01T00:00:00Z --max-steps 5000 --output-dir results_m06r
```

Inne profile: `--mode MVP`, `--mode SMC`, `--mode SCALPING`. `AUTO` ma jawną kolejność SMC → MVP → Scalping. `--step-tf M5` zapewnia częste sprawdzanie; `M15` przyspiesza przegląd, ale **pomija część M5 triggerów** — do ewaluacji Scalping zaleca się M5.

**Opcjonalny punktowy kontekst wiadomości M04N/M06H:**

```powershell
py -3 M06R_HISTORICAL_REPLAY.py --bars-dir data_mt5_six_tf --mode AUTO --macro-events runtime_m06h/M04N_HISTORY.jsonl --macro-config M06H_RESEARCH_CONFIG.example.json --output-dir results_m06r
```

Archiwum musi zawierać migawki faktycznie zapisane przed momentem sygnału. Dzisiejszy kalendarz nie zastępuje historii dawnych prognoz i godzin publikacji. Brak wpisu nigdy nie oznacza świadomej zgody na transakcję.

## 3. Szybki test bez terminala

```powershell
py -3 M06R_MAKE_SYNTHETIC_DEMO.py --output-dir examples/SYNTHETIC_SIX_TF --bars 260
py -3 M06R_HISTORICAL_REPLAY.py --bars-dir examples/SYNTHETIC_SIX_TF --min-closed 230 --max-steps 3 --output-dir examples/SYNTHETIC_RESULT
```

Te dane **nie są notowaniami XAUUSD**. Wynik zerowy nie dowodzi, że strategia nie działa, a potwierdzenia na wymyślonych danych nie są dowodem przewagi.

## 4. Pliki wynikowe

- `M06R_REPLAY_REPORT.json`: status, pokrycie historyczne, liczniki kandydatów i przejść, jawne ograniczenia.
- `M06R_STAGE_LEDGER.jsonl`: zdarzenia punktowe `EARLY_SETUP`, `SETUP_FORMING`, `QUALIFIED`, `ARMED`, `TRIGGERED`, `CONFIRMED`, `INVALIDATED`, `EXPIRED`, `GAP_REVIEW` — tylko gdy wystąpią.
- `M06R_CONFIRMED_SIGNALS.jsonl`: **analityczne** sygnały do dalszych testów. Pola `entry`, `stop_loss`, `take_profit` i koszty świadomie ustawiono na `null`/`NOT_RUN`.
- `M06R_REPORT_PL.md`: polskie podsumowanie.

**Ważne: sam ten dziennik nie jest jeszcze gotowym pakietem transakcyjnym M06.** Żeby rozliczyć wyniki netto, trzeba wyznaczyć i zamrozić obiektywny plan wykonania (Entry, SL, TP, czas ważności), pozyskać historyczne ticki Bid/Ask, prowizję, poślizg i parametry kontraktu brokera, a potem uruchomić M06/M06H z poprawnym OOS. Nie wolno przypisywać ceny wejścia na podstawie świecy, na której dopiero powstało potwierdzenie.

## 5. Kontrole bezpieczeństwa i metodologii

- Odrzucane są duplikaty, cofnięty czas, niewłaściwe symbole, świeca `FORMING`, nieprawidłowe OHLC, niepoprawne volume, dostępność przed zamknięciem oraz niezgodność SHA-256 z manifestem.
- Wskaźniki i struktura są obliczane tylko na danych `available_at <= replay_as_of`.
- Zamknięta świeca jest dostępna w eksporcie konserwatywnie dopiero po początku kolejnego bar-u brokera; ostatnia po granicy zakresu eksportu. Po przerwie sesyjnej taka polityka celowo opóźnia dostępność.
- Stare dane i niewystarczająca historia przechodzą do `PENDING`; braków nie uzupełnia się sztucznymi świecami.
- Reguły M07 to **niezoptymalizowane parametry badawcze**; dla każdej fazy wymagany jest nowy zamknięty bar M5/M15, unieważnienie ma priorytet.
- Zmiana zarejestrowanej hipotezy nie restartuje faz setupu; przerwa w wymaganych barach kończy hipotezę `GAP_REVIEW`.
- Żaden CSV/JSON nie może przyznać prawa do handlu. `execution_permission=BLOCKED` zawsze.
- SHA-256 chroni integralność plików po eksporcie, **nie poświadcza autentyczności serwera brokera**.

## 6. Zakres i dalszy etap

Testy offline sprawdzają kod i zgodność z modułami; nie sprawdzają rentowności ani rzeczywistego terminala użytkownika. Po zebraniu danych z MT5 należałoby oddzielnie przeprowadzić walidację kompletności poszczególnych timeframe, chronologiczne OOS i forward DEMO. Moduły produkcyjne M01/M08/M11/M14 nadal zarządzają własnymi wymaganiami; M06R nie omija żadnej ich blokady.

Status: `CANDIDATE / PENDING APPROVAL`.
