# M10A — kontrakt integracyjny v1.1.0 (CANDIDATE)

## Granice modułu

`RUN_MT5_AUTOMATIC_TRIGGER_READONLY.py` korzysta z dotychczasowego procesu `RUN_MT5_READONLY_SIGNAL_LIFECYCLE.py`, który zbiera migawkę MT5 i wykonuje M01/M02/M02I/M03E/M09/M10. Następnie `M10_AUTO_TRIGGER_CONFIRM.advance()` analizuje **jeden najnowszy zamknięty bar setup TF**, bez odczytywania screenshotów, tworzenia zleceń ani zmiany pozostałych silników.

Schemat rezultatów pozostaje `2.0.0`, globalny prompt `4.1.0`; warstwa adaptera ma wersję `1.1.0-CANDIDATE`. Każda konfiguracja reguł jest wiązana hashem z `setup_id` w bazie M10. Wersja `strategy_id` musi być wcześniej zamrożona w M07; sam hash lokalny nie stanowi atestacji M08.

## Przejścia

| Bieżący stan | Zdarzenie M10 | Wymagany warunek |
|---|---|---|
| EARLY_SETUP | QUALIFY lub DEVELOPMENT | Inny zamknięty bar po CORE_READY, jawna reguła |
| SETUP_FORMING | QUALIFY | Własna reguła, nowy bar |
| QUALIFIED | ARM | Własna reguła, nowy bar |
| ARMED | TRIGGER | Własny trigger, nowy bar, MT5 |
| TRIGGERED | CONFIRM | Zamknięcie **późniejszego** baru oraz wymagane bramki M10 |
| Dowolny przed wejściem | INVALIDATE | Jawne zamknięcie poza poziomem invalidation, pierwszeństwo przed powyższymi |
| EXPIRED / INVALIDATED / pozostały terminalny | Brak awansu | Bez wskrzeszania setup_id |

Funkcja `advance(report,snapshot,quote,strategy_plan,db_path, now=..., direct_mt5=True,connected=True)` może ustawiać `direct_mt5=True` **wyłącznie w lokalnym czytniku mającym dostęp do wyniku wywołania prawdziwego terminala**. Taka flaga w JSON zewnętrznym nie stanowi zaufanego dowodu. Bez pozytywnego lokalnego audytu M01 i ważnych M03E pięciu CORE nie są tworzone przejścia.

## Zapis i odzyskanie

Do istniejącej bazy SQLite `M10_STATE.sqlite` dodawane są tabele `m10auto_policy` i `m10auto_ledger`. Zmiana rekordu M10, zapis zdarzenia i jego deduplikacja odbywają się w jednej transakcji SQLite. Dla tej samej świecy pod ponownym uruchomieniem: `DUPLICATE_SKIPPED`. Przy próbie zmiany wcześniej ocenionej świecy: `HISTORICAL_BAR_REVISION_REQUIRES_REVIEW`. Gdy pomiędzy kolejnymi ocenianymi świecami jest luka w interwale śróddziennym: `UNREPLAYED_CLOSED_BAR_GAP` — przejście wstrzymane zamiast fikcyjnego odtworzenia brakujących zdarzeń. D1 podlega specjalnemu kalendarzowi M10.

Zmiana `lifecycle_rules`/invalidation w obrębie tego samego setup_id: `FROZEN_LIFECYCLE_RULES_CHANGED_NEW_VERSION_REQUIRED`. Szablon `LIFECYCLE_RULES.example.json` z `example_only=true` nie jest akceptowany jako operacyjny sygnał.

## M14 / konto Zero / wykonanie

Adapter przekazuje zweryfikowany stan M10 do niezmienionego `M14_REFERENCE_DECISION_ENGINE.evaluate()`; nie zamienia samodzielnie `CONFIRMED` w decyzję LONG/SHORT. M14 jest zawsze uruchamiany w środowisku `ANALYSIS_ONLY`. Brak zatwierdzonej strategii, M11, brokera, prowizji lub pełnej ceny planu nie kasuje analitycznej fazy, ale pozostawia `execution_permission=BLOCKED`, `execution_eligible=false`, `live_execution_allowed=false`, `submitted_order_id=null`, `broker_order_sent=false`.

MT5 Zero oznacza zadeklarowany typ rachunku: rzeczywisty Bid/Ask, prowizja, swap i poślizg pozostają do odczytu z MT5. TradingView jest tylko uzupełnieniem kontekstu i nie może potwierdzić zamknięcia świecy triggera. Brak mechanizmu order_send.

## Testy, których tu nie wykonano

Prawdziwy terminal Windows, realne kontrakty i historia M06, testy opóźnień/downtime brokera, formalne zamrożenie specyfikacji M07/M08, osobne pełne detektory SMC per strategia, backtest OOS i forward DEMO. Wszystkie testy w paczce są syntetyczne lub regresyjne.
