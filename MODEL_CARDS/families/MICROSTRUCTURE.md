# Karta modelu – MICROSTRUCTURE

**Mikrostruktura – arkusz brokera (imbalance, OFI, microprice) + klasyfikator reakcji**

| Pole | Wartość |
|---|---|
| Rodzaj | MEASUREMENT (trening klasyfikatora reakcji (opcjonalny)) |
| Zadanie | BOOK_STATE_AND_REACTION_10S – typ PMW-PRED-2 `MICROSTRUCTURE`, jednostka `mixed` |
| Interwał / horyzonty | – / brak (pomiar stanu) |
| Środowisko | MAIN (sklearn) |
| Dane | L2_BOOK, IndicatorService.book_snapshots (market_book_get) |
| Odbiorcy | SH_CONTEXT:entry_quality, RISK:execution_conditions, PANEL:microstructure |
| Role | OFF = nie liczy; SHADOW = liczy i zapisuje, rola OBSERVE (bez wpływu); ASSIST = tylko po walidacji APPROVED na danych REAL – może wyłącznie wstrzymać wejście (SH: READY→WAIT, ACTIVE: węzeł MODELS); REQUIRED = `config.decision.required_models` – brak / nieświeża / przeciwna prognoza blokuje nowe wejście. Żadna rola nie tworzy wejścia ani nie podnosi WAIT. |

## Walidacja

Bramka promocji liczona wyłącznie na części rozwojowej (walidacja), holdout raportowany osobno; kryteria muszą być spełnione, inaczej artefakt ma stan VALIDATION_FAILED i nie może dostać roli ASSIST.

Kontrola potoku na danych SYNTETYCZNYCH (`tools/validate_families_synthetic.py`, profil smoke): **APPROVED**

| Kryterium | Próg | Wartość | Spełnione |
|---|---|---|---|
| val_skill | > 0.0 | 0.0367703 | tak |

## Ograniczenia

* Ocena na danych historycznych nie jest obietnicą wyniku; READY oznacza zdolność zwrócenia wyniku, nie zgodę na handel.
* Model nie składa zleceń; wynik niedostępny (BLOCKED_DATA / STALE / ERROR) nie ma wartości i nie jest traktowany jak neutralny.
* Dane syntetyczne służą wyłącznie do sprawdzenia potoku – rola ASSIST wymaga walidacji na Twoich danych REAL z MT5.
