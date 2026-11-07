# Karta modelu – SEQ_GRU_EVENT

**Event GRU (istniejący mm/event_engine) – adapter**

| Pole | Wartość |
|---|---|
| Rodzaj | PRETRAINED_ADAPTER (trening w Centrum MM (mm/event_engine)) |
| Zadanie | EVENT_UNITS_DIR3 – typ PMW-PRED-2 `CLASS_PROBABILITIES`, jednostka `probability` |
| Interwał / horyzonty | EVENT / 1 |
| Środowisko | MAIN (bez dodatkowych bibliotek) |
| Dane | EVENTS, EVENT_UNITS_V1, jednostki zdarzeń (inne niż świece) – wagi niezamienne z SEQ_GRU |
| Odbiorcy | PANEL:model_status, MM_BOARD:evidence |
| Role | OFF = nie liczy; SHADOW = liczy i zapisuje, rola OBSERVE (bez wpływu); ASSIST = tylko po walidacji APPROVED na danych REAL – może wyłącznie wstrzymać wejście (SH: READY→WAIT, ACTIVE: węzeł MODELS); REQUIRED = `config.decision.required_models` – brak / nieświeża / przeciwna prognoza blokuje nowe wejście. Żadna rola nie tworzy wejścia ani nie podnosi WAIT. |

## Walidacja

Bramka promocji liczona wyłącznie na części rozwojowej (walidacja), holdout raportowany osobno; kryteria muszą być spełnione, inaczej artefakt ma stan VALIDATION_FAILED i nie może dostać roli ASSIST.

Trenowany poza magazynem rodzin: trainhub (test_trainhub) / centrum MM.

## Ograniczenia

* Ocena na danych historycznych nie jest obietnicą wyniku; READY oznacza zdolność zwrócenia wyniku, nie zgodę na handel.
* Model nie składa zleceń; wynik niedostępny (BLOCKED_DATA / STALE / ERROR) nie ma wartości i nie jest traktowany jak neutralny.
* Dane syntetyczne służą wyłącznie do sprawdzenia potoku – rola ASSIST wymaga walidacji na Twoich danych REAL z MT5.
