# MasterQUO M06H 1.0.0 — audyt i changelog

**Wydanie:** 2026-10-08. Status `CANDIDATE / PENDING APPROVAL`. Inne moduły MasterQUO pozostają bez zmian. Brak wykonywania zleceń.

## Implementacja

- `M06H_RESEARCH_ENGINE.py` — zamrożone foldy development/validation/FINAL_OOS, opisowy event-study na zamknięciach M1, walidacja czasu i braków, porównanie z dopasowanymi kontrolami, bootstrap blokami dni; makro filtr znany **w chwili powstania sygnału**.
- Oryginalny `vendor/M06_REFERENCE_ENGINE.py` jest bajtowo skopiowany z istniejącej paczki M06. Na wejściu z historycznym signal ledger i prawdziwymi kwotowaniami oryginalny M06 oblicza PnL NETTO, prowizje, spread przez Bid/Ask, poślizg i metryki foldów. Bez ledger i quote packet taka symulacja nie jest uruchamiana.
- `M06H_ARCHIVE_M04N.py` + `M06H_ARCHIVE_WATCH.py` — append-only audit trail kopii raportu M04N, kontrola czasu zapisu i łańcuch SHA256, bez nadpisywania wcześniejszej treści. Nie jest uwierzytelnionym zewnętrznym źródłem czasu.
- `M06H_EXPORT_MT5_READONLY.py` — historyczne świece XAUUSD M1 z `MT5.copy_rates_range` (UTC, brak screenshot/OCR).
- `M06H_EXPORT_MT5_TICKS_READONLY.py` — historyczne ticki z `MT5.copy_ticks_range` z czasem msec, spreadem przez kwotowania; deduplikacja i poprawność Bid/Ask, brak `order_send`.
- `M06H_MAKE_SYNTHETIC_DEMO.py`, `examples/*` — jedynie dane syntetyczne z oznaczeniami; `execution_permission=BLOCKED`.

## Weryfikacja

- `py -3 -m unittest -q M06H_TESTS` — **76/76 PASS** w środowisku offline. Kontrole: konfiguracja, timezone/DST formatu ISO, kompletność M1, błędne OHLC i świeca FORMING, konflikty/revisions kalendarza, portalowe duplikaty, budowanie/zapis archiwum, przyszłe zmiany ważności, walk-forward/OOS, kosztowe M06 quote-replay (symulacja), blokada synthetic, eksport M1 i ticków oraz brak wywołań `order_send`.
- DEMO CLI — wygenerowano `M06H_VALIDATION_REPORT.json` i `M06H_REPORT_PL.md`, 6 badawczych wierszy event-study dla dwóch **wymyślonych** zdarzeń i 1260 sztucznych świec; `strategy_validation=SYNTHETIC_DEMONSTRATION_ONLY`, brak zgody na handel.
- Przykładowe wyjście sprawdzono pod kątem obowiązkowych kluczy kontraktu oraz schema JSON.

## NOT RUN / ograniczenia

- Realny terminal MetaTrader 5 użytkownika na Windows i historyczny broker tick replay: **NOT RUN**. Nie ma jego danych, parametrów prowizji i poślizgu ani rachunku.
- Realne wyniki MVP, SMC i SCALPING (OOS, expectancy, win rate, profit factor): **NOT RUN**, ponieważ nie dostarczono autentycznego point-in-time dziennika sygnałów i pełnej serii ticków.
- Zewnętrzna weryfikacja wiarygodności archiwum FF/MM i pełnego kalendarza FOMC/BEA: **NOT RUN**. Kalendarze M04N pozostają częściowe i podatne na rewizje.
- Testy jednostkowe i syntetyczne przykłady **nie potwierdzają ekonomicznej przewagi ani poprawnego działania na rynku LIVE**. Użycie do ryzyka w M04/M11/M14 i monitor M15 wymaga osobnego, jawnego zatwierdzenia po forward DEMO.

## Zabezpieczenia

- Brak backfillu przyszłej wiedzy; do blokady makro liczy się `known_at` i `impact_known_at`, a nie przyszły poprawiony feed.
- Brak wyciągania wniosków z wielokrotnie zaliczonych tych samych publikacji FF/MM; konflikt dat dla tej samej publikacji danego dnia powoduje wykluczenie.
- Zmiany w raporcie nie aktualizują istniejących strategii ani M08. Default HIGH pre30/post15 i EXTREME pre60/post30 to scenariusz prerejestrowany, nie optimum.
- `approval_status=PENDING_APPROVAL`, `execution_permission=BLOCKED`, `live_execution_allowed=false`, `orders_sent=0`.
