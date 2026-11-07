# Karta modelu – KALMAN_LS

**Filtr Kalmana poziom + nachylenie (rozbudowa mm_kalman)**

| Pole | Wartość |
|---|---|
| Rodzaj | ESTIMATED (estymacja Q/R) |
| Zadanie | TREND_STATE – typ PMW-PRED-2 `FILTER_STATE`, jednostka `mixed` |
| Interwał / horyzonty | M5 / 1 |
| Środowisko | MAIN (bez dodatkowych bibliotek) |
| Dane | BARS, M5, ≥ 600 świec |
| Odbiorcy | SH_CONTEXT:trend_state, STRATEGY:regime_context, PANEL:model_status |
| Role | OFF = nie liczy; SHADOW = liczy i zapisuje, rola OBSERVE (bez wpływu); ASSIST = tylko po walidacji APPROVED na danych REAL – może wyłącznie wstrzymać wejście (SH: READY→WAIT, ACTIVE: węzeł MODELS); REQUIRED = `config.decision.required_models` – brak / nieświeża / przeciwna prognoza blokuje nowe wejście. Żadna rola nie tworzy wejścia ani nie podnosi WAIT. |

## Walidacja

Bramka promocji liczona wyłącznie na części rozwojowej (walidacja), holdout raportowany osobno; kryteria muszą być spełnione, inaczej artefakt ma stan VALIDATION_FAILED i nie może dostać roli ASSIST.

Kontrola potoku na danych SYNTETYCZNYCH (`tools/validate_families_synthetic.py`, profil smoke): **APPROVED**

| Kryterium | Próg | Wartość | Spełnione |
|---|---|---|---|
| z_std_ok | > 0.5 | 1 | tak |

## Ograniczenia

* Ocena na danych historycznych nie jest obietnicą wyniku; READY oznacza zdolność zwrócenia wyniku, nie zgodę na handel.
* Model nie składa zleceń; wynik niedostępny (BLOCKED_DATA / STALE / ERROR) nie ma wartości i nie jest traktowany jak neutralny.
* Dane syntetyczne służą wyłącznie do sprawdzenia potoku – rola ASSIST wymaga walidacji na Twoich danych REAL z MT5.
