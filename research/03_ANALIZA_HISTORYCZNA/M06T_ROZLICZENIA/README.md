# MasterQUO M06T v1.0.0 — Trade Settlement & Out-of-Sample Research (CANDIDATE)

## Cel

Łączy **M06R historical replay** (`M06R_CONFIRMED_SIGNALS.jsonl` + `M06R_STAGE_LEDGER.jsonl`) z historycznymi, dostarczonymi przez użytkownika kwotowaniami **Bid/Ask XAUUSD MT5** i niezmienionym referencyjnym M06. Ocenia niezależne hipotetyczne wejścia LONG/SHORT, stop/target, prowizję, poślizg oraz oddzielną próbę OOS. Opcjonalny kalendarz M06H umożliwia porównanie wyników przed/po filtrze makro, wyłącznie na informacjach dostępnych w chwili sygnału.

**Nie jest systemem transakcyjnym.** Nie łączy się z kontem w celu składania zleceń. Przeliczone kwotowania nie stanowią rzeczywistych filli. Materiały syntetyczne nie są dowodem rentowności. Wydanie `CANDIDATE/PENDING APPROVAL`, `execution_permission=BLOCKED`, `live_eligible=false`.

## Pliki

- `M06T_ENGINE.py` — główny adapter; walidacja, mapowanie zamrożonych scenariuszy na M06, rozliczanie, raporty OOS, makro.
- `vendor/M06_REFERENCE_ENGINE.py` — **niezmieniony** M06; oblicza wyniki netto historycznych kwotowań.
- `vendor/M06H_RESEARCH_ENGINE.py` — **niezmieniony** importer archiwum wydarzeń M06H.
- `M06H_EXPORT_MT5_TICKS_READONLY.py` — read-only eksport ticków brokera, do 7 dni na zadanie.
- `M06T_MAKE_SYNTHETIC_DEMO.py` — testowy generator fikcyjnych ticków/sygnałów i kosztów; nie zawiera wyników rzeczywistych.
- `M06T_TESTS.py` — testy integralności, opóźnienia danych, zamrożenia reguł i rozliczeń.
- `M06T_OUTPUT_SCHEMA.json` — schemat wynikowego raportu.
- `PROTOCOL_TEMPLATE_EDIT_BEFORE_USE.json` — **celowo `frozen=false`**; uzupełnij i zarejestruj parametry przed testem. Przykładowe poziomy i prowizje NIE są parametrami optymalnymi.

## 1. Test demonstracyjny — nie wymaga instalacji MT5

Windows / PowerShell, po rozpakowaniu:

```powershell
py -3 -m unittest M06T_TESTS -v
py -3 M06T_MAKE_SYNTHETIC_DEMO.py
py -3 M06T_ENGINE.py --signals examples/SYNTHETIC_ONLY/SIGNALS_SYNTHETIC.jsonl --ledger examples/SYNTHETIC_ONLY/STAGES_SYNTHETIC.jsonl --ticks examples/SYNTHETIC_ONLY/TICKS_SYNTHETIC.csv --protocol examples/SYNTHETIC_ONLY/PROTOCOL_SYNTHETIC.json --events examples/SYNTHETIC_ONLY/MACRO_SYNTHETIC.json --replay-report examples/SYNTHETIC_ONLY/M06R_REPORT_SYNTHETIC.json --out-dir examples/SYNTHETIC_ONLY/RESULTS
```

Albo kliknij `START_SYNTHETIC_DEMO.bat`. Raport jest zawsze oznaczony `RESEARCH_ONLY`. Dla syntetycznego kalendarza wynik filtra makro jest `NOT_RUN` — nie symuluje realnej skuteczności filtra.

## 2. Dane rzeczywiste — MT5 DEMO

Na Windows z uruchomionym terminalem MT5 i dostępną historią tickową:

```powershell
py -3 -m pip install MetaTrader5
py -3 M06H_EXPORT_MT5_TICKS_READONLY.py --symbol XAUUSD --from-utc 2026-09-01T00:00:00Z --to-utc 2026-09-08T00:00:00Z --output data/XAUUSD_TICKS_01.csv
```

Eksport jest ograniczony do **7 dni jednorazowo**. Dla dłuższego okresu wygeneruj kolejne pliki i podaj je w kolejności chronologicznej po `--ticks`. Broker może nie posiadać pełnej historii tickowej. Eksport nie potwierdza czasu otrzymania ticków przez Twoją aplikację ani jakości rzeczywistego fillu.

W odrębnej paczce M06R uruchom replay na 6 eksportach timeframe i zachowaj pliki:

- `M06R_CONFIRMED_SIGNALS.jsonl`
- `M06R_STAGE_LEDGER.jsonl`
- `M06R_REPLAY_REPORT.json` — zalecany do krzyżowego sprawdzenia wszystkich wierszy

Uzupełnij `PROTOCOL_TEMPLATE_EDIT_BEFORE_USE.json`: exact symbol, zweryfikowane koszty konta Zero, mnożnik wartości 1 punktu ceny na 1 lot, `strategy_version` identyczne jak w M06R, `spec_hash`, zamrożone przed odkryciem setupów `frozen_at`, reguły odległości SL/TP i wolumen oraz niepokrywające się zakresy DEVELOPMENT / FINAL_OOS. Ustaw `frozen=true` **wyłącznie po rzeczywistym zatwierdzeniu parametrów**. Pozostaw `research_only=true`. Historia dat modyfikacji pliku nie jest dowodem rejestracji ex ante.

Przykładowe wywołanie na własnych danych:

```powershell
py -3 M06T_ENGINE.py --signals results_m06r/M06R_CONFIRMED_SIGNALS.jsonl --ledger results_m06r/M06R_STAGE_LEDGER.jsonl --ticks data/XAUUSD_TICKS_01.csv data/XAUUSD_TICKS_02.csv --protocol PROTOCOL_FROZEN.json --events data/M04N_HISTORY.jsonl --replay-report results_m06r/M06R_REPLAY_REPORT.json --out-dir results_m06t
```

`--events` jest opcjonalny. Bez archiwum faktycznie obserwowanego w czasie historycznym moduł zapisze `macro_comparison.status=NOT_RUN`; **nie zakłada braku ważnych publikacji**. M06H obsługuje archiwum migawek M04N `.jsonl` oraz kuratorowany plik zdarzeń. Kalendarz wyłącznie syntetyczny także daje `NOT_RUN`.

## 3. Jak budowana jest hipotetyczna transakcja

1. Każdy sygnał `CONFIRMED` musi mieć zapis faz `EARLY_SETUP → SETUP_FORMING → QUALIFIED → ARMED → TRIGGERED → CONFIRMED` z narastającymi znacznikami czasu i spójną strategią.
2. Konfiguracja strategii musi być zadeklarowana jako zamrożona **przed wykryciem `EARLY_SETUP`**. Nie daje to samodzielnie kryptograficznego dowodu rejestracji ex ante.
3. Referencyjna cena dla badawczych poziomów SL/TP jest środkiem **ostatniego historycznie znanego kwotowania** dostępnego do chwili potwierdzenia. Odległości SL/TP i wolumen są zamrożonymi parametrami badawczymi, nie poziomami optymalizowanymi wstecz.
4. Zachowany M06 wybiera następny dostępny tick jako hipotetyczny market fill: **LONG po ask + slippage, SHORT po bid − slippage**. Dla wyjścia stosuje odpowiednio bid/ask; prowizja per side i swap są rozliczane zgodnie z konfiguracją M06.
5. Bez kolejnego ticka, z nieważnym bracketingiem, luki cenowej, zbyt małą próbką OOS albo przy nieznanym koszcie bot nie nadaje statusu zweryfikowanej rentowności.
6. Wyniki nie uwzględniają głębokości rynku, częściowych wykonań, opóźnienia transmisji ani prawdziwego odrzucenia zlecenia. Wyniki niezależnych transakcji nie stanowią symulacji portfela, a overlapping trade positions nie są modelowane jako stan konta.

## 4. Wyniki

- `M06T_REPORT.json` — koszty netto, profil strategii, DEV/OOS, wejścia/wyjścia hipotetyczne, źródła makro, ostrzeżenia, SHA256 wejścia.
- `M06T_REPORT_PL.md` — skrócony raport po polsku.

W raporcie stany `NO_FILL`, `UNRESOLVED`, `PURGED_BOUNDARY`, `COST_UNKNOWN`, `UNVERIFIED_TICK_GAP`, `OUTSIDE_FOLD` nie są liczone jako zakończone transakcje. Nie ma możliwości autoryzacji LIVE. Wyniki porównania makro to selekcja próby i **nie są dowodem przyczynowego wpływu informacji na rentowność**.

## 5. Ograniczenia i plan weryfikacji

- Pliki historyczne CSV/JSONL są niezaufane (brak atestacji brokera); `source_id=MT5_...` nie wystarcza do certyfikacji.
- Jeśli symbole XAUUSD i `XAUUSDm` się różnią, wszystkie pliki i protokół muszą używać tego samego exact symbol.
- Przykładowa `money_per_price_unit_per_lot=100` i prowizja `2.5` są **hipotezami**, nie zweryfikowanym parametrem Twojego brokera.
- Nie ma weryfikacji dostępności historycznych newsów poza znacznikami archiwum; brak wydarzeń w kalendarzu nie potwierdza bezpieczeństwa handlu.
- Konieczne oddzielne: bieżące testy jakości feedu MT5, prawdziwa komisja/prowizja i koszt symbolu, sanity test fill/latency, walk-forward oraz forward DEMO.
- Bez sygnałów M06R wystąpi `NOT_RUN` zamiast urojonych statystyk.
- Nie używaj danych syntetycznych do oceny prawdopodobieństwa zysku.
