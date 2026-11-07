# Karta modelu – TS_ARIMA

**ARIMA (statsmodels) – prognoza log-zwrotu**

| Pole | Wartość |
|---|---|
| Rodzaj | TRAINED (trening) |
| Zadanie | LOG_RETURN_H – typ PMW-PRED-2 `REGRESSION`, jednostka `log_return` |
| Interwał / horyzonty | M5 / 1, 3, 5 |
| Środowisko | MAIN (statsmodels, pandas, scipy) |
| Dane | BARS, M5, ≥ 800 świec, eksport MT5 (marketdata Store) / bridge na żywo |
| Odbiorcy | SH_CONTEXT:expected_move, PANEL:model_status, AGENT:context |
| Role | OFF = nie liczy; SHADOW = liczy i zapisuje, rola OBSERVE (bez wpływu); ASSIST = tylko po walidacji APPROVED na danych REAL – może wyłącznie wstrzymać wejście (SH: READY→WAIT, ACTIVE: węzeł MODELS); REQUIRED = `config.decision.required_models` – brak / nieświeża / przeciwna prognoza blokuje nowe wejście. Żadna rola nie tworzy wejścia ani nie podnosi WAIT. |

## Walidacja

Bramka promocji liczona wyłącznie na części rozwojowej (walidacja), holdout raportowany osobno; kryteria muszą być spełnione, inaczej artefakt ma stan VALIDATION_FAILED i nie może dostać roli ASSIST.

Kontrola potoku na danych SYNTETYCZNYCH (`tools/validate_families_synthetic.py`, profil smoke): **APPROVED**

| Kryterium | Próg | Wartość | Spełnione |
|---|---|---|---|
| converged | > 0.5 | 1 | tak |
| stable | > 0.5 | 1 | tak |
| val_skill_vs_zero | > 0.0 | 0.0358617 | tak |

## Ograniczenia

* Ocena na danych historycznych nie jest obietnicą wyniku; READY oznacza zdolność zwrócenia wyniku, nie zgodę na handel.
* Model nie składa zleceń; wynik niedostępny (BLOCKED_DATA / STALE / ERROR) nie ma wartości i nie jest traktowany jak neutralny.
* Dane syntetyczne służą wyłącznie do sprawdzenia potoku – rola ASSIST wymaga walidacji na Twoich danych REAL z MT5.
