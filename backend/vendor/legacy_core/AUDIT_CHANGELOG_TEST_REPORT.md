# MasterQUO M01/M03E/M10 — Audit i raport v1.0.0-CANDIDATE

**Zakres:** lokalny read-only Data Integrity Gate M01, przepływ M03E (pięć CORE), lokalna trwałość M10; z zachowaniem wcześniejszych silników M01/M02/M02I/M03/M09/M10/M14 i ich wersji. Globalne `schema_version=2.0.0`, `prompt_version=4.1.0` bez zmian.

## Nowość

1. Audyt M01: MT5: wyłącznie BID historyczne OHLC, Bid/Ask aktualne, provenance, zegary, zamknięte bary, bar uniqueness i chronological ordering, świeżość, ograniczone wykrywanie luk/warunków sesji, histogram TF. FAIL vs PENDING, bez wymyślania świec.
2. Wspólna migawka w M02/M02I/M03, zachowane profile wybranych przez użytkownika indykatorów XAUUSD i opcjonalnego DXY H1.
3. M03E: niepromowanie wskaźników do CORE, wymóg faktycznych evidence ID FVG/OB/LEVEL/SWEEP + zamrożonych identyfikatorów strategii; warunki development/invalidation zapisane jako operatory na obserwowalnych poziomach.
4. M09/M14: decyzja analityczna i niezależne `execution_permission=BLOCKED`.
5. M10: SQLite state machine, stabilne ID, dedup eventów CORE_READY, licznik zamkniętych świec TTL; bez automatycznych TRIGGER/CONFIRM i bez brokera execution adapter.
6. Proces Windows `RUN_MT5_READONLY_SIGNAL_LIFECYCLE.py`: odświeżanie kwotowań, zamkniętych świec i historii; gdy dane tracą aktualność, `NO_TRADE/BLOCKED`. Obliczenia zamkniętych świec cache'owane między zamknięciami.
7. Eksport JSON, schemat, profile, instrukcja i testy offline.

## Krytyczne ograniczenia

- Odczyt i integracja to **kandydat do badań**; `PASS_WITH_LIMITATIONS` M01 oznacza lokalną kontrolę integralności po bezpośrednim read-only odczycie MT5, nie pełną certyfikację pochodzenia notowań. Weryfikacja kalendarza sesji, instrumentu CFD u brokera i niezależna kontrola przed LIVE wymagają pracy.
- `ZERO_SPREAD` jest profilem deklarowanym. Rzeczywiste spread, prowizje, opłaty, swap, poślizg i fill model nie zostały potwierdzone.
- Przykład syntetyczny nie ma M03 liquidity/POI, dlatego poprawny wynik to `WAIT`, a nie LONG/SHORT. Bez uzupełnionych reguł strategii i realnych CORE M10 nie otrzyma EARLY.
- `M10` automatyzuje tylko badawcze `CANDIDATE→EARLY_SETUP` przy istniejących CORE i lokalnym health; nie automatyzuje pełnych przejść QUALIFIED/ARMED/TRIGGERED/CONFIRMED ani modelu Entry/SL/TP.
- Rzeczywisty MT5 użytkownika nie jest dostępny w tej sesji. **Nie wykonano rzeczywistego TEST DEMO/LIVE, testu strategii OOS, forward i broker-order reconciliation.** Wszelkie wyniki testów są offline, syntetyczne.
- Żadnych zleceń, screenshotów, OCR, Telegram tokenów, OpenAI klucza lub autoryzacji LIVE.

## Weryfikacja

Uruchom `py RUN_ALL_OFFLINE_TESTS.py`. Raport zawiera liczbę i status testów nowego integratora, starego mostu oraz modułów M01, M02, M02I, M03, M09, M10, M14. `jsonschema` jest opcjonalnym narzędziem sprawdzania syntetycznego przykładu.

Założenie: testy z FakeMT5 mogą potwierdzić poprawność interfejsu i zabezpieczeń, nie rzeczywistą skuteczność sygnałów na XAUUSD.

## Dalsze etapy

- Faktyczna walidacja profilów sesji MT5, spreadu/prowizji i trwałości danych na użytkownika terminalu Windows.
- Strategia M07/M08: zamrożone operacyjne reguły wykrywania POI/triggera, certyfikacja spec_hash, historyczny backtest M06 i DEMO forward.
- Dedykowany detektor M10 triggerów/confirmation ze znaną wersją i warunkami cenowymi; podłączenie M15 dopiero do walidowanych sygnałów.
- Integracja M11/M14, autoryzacja i uzgadnianie broker fills osobnym, zatwierdzonym etapem.
