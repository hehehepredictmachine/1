# Karta modelu – BREAKOUT

**Breakout – wspólny moduł logiki wybicia (kanał, kompresja, potwierdzenie, retest)**

| Pole | Wartość |
|---|---|
| Rodzaj | VALIDATED_RULES (walidacja parametrów) |
| Zadanie | BREAKOUT_STATE – typ PMW-PRED-2 `FILTER_STATE`, jednostka `mixed` |
| Interwał / horyzonty | M5 / 1 |
| Środowisko | MAIN (bez dodatkowych bibliotek) |
| Dane | BARS, M5, ≥ 1500 świec |
| Odbiorcy | SH_CONTEXT:breakout_state, STRATEGY:S05/S12 BREAKOUT_RETEST context, PANEL:model_status |
| Role | OFF = nie liczy; SHADOW = liczy i zapisuje, rola OBSERVE (bez wpływu); ASSIST = tylko po walidacji APPROVED na danych REAL – może wyłącznie wstrzymać wejście (SH: READY→WAIT, ACTIVE: węzeł MODELS); REQUIRED = `config.decision.required_models` – brak / nieświeża / przeciwna prognoza blokuje nowe wejście. Żadna rola nie tworzy wejścia ani nie podnosi WAIT. |

## Walidacja

Bramka promocji liczona wyłącznie na części rozwojowej (walidacja), holdout raportowany osobno; kryteria muszą być spełnione, inaczej artefakt ma stan VALIDATION_FAILED i nie może dostać roli ASSIST.

Kontrola potoku na danych SYNTETYCZNYCH (`tools/validate_families_synthetic.py`, profil smoke): **APPROVED**

| Kryterium | Próg | Wartość | Spełnione |
|---|---|---|---|
| dev_expectancy_after_cost | > 0.0 | 0.593508 | tak |
| dev_trades | > 19.0 | 24 | tak |

## Ograniczenia

* Ocena na danych historycznych nie jest obietnicą wyniku; READY oznacza zdolność zwrócenia wyniku, nie zgodę na handel.
* Model nie składa zleceń; wynik niedostępny (BLOCKED_DATA / STALE / ERROR) nie ma wartości i nie jest traktowany jak neutralny.
* Dane syntetyczne służą wyłącznie do sprawdzenia potoku – rola ASSIST wymaga walidacji na Twoich danych REAL z MT5.
