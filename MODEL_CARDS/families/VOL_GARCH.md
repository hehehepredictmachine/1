# Karta modelu – VOL_GARCH

**GARCH(1,1) (arch) – zmienność warunkowa**

| Pole | Wartość |
|---|---|
| Rodzaj | TRAINED (trening) |
| Zadanie | SIGMA_LOG_RETURN_H – typ PMW-PRED-2 `VOLATILITY`, jednostka `sigma_return` |
| Interwał / horyzonty | M5 / 1, 6, 12 |
| Środowisko | MAIN (arch, scipy) |
| Dane | BARS, M5, ≥ 1000 świec |
| Odbiorcy | RISK:volatility_scenario, SH_CONTEXT:volatility, PANEL:model_status |
| Role | OFF = nie liczy; SHADOW = liczy i zapisuje, rola OBSERVE (bez wpływu); ASSIST = tylko po walidacji APPROVED na danych REAL – może wyłącznie wstrzymać wejście (SH: READY→WAIT, ACTIVE: węzeł MODELS); REQUIRED = `config.decision.required_models` – brak / nieświeża / przeciwna prognoza blokuje nowe wejście. Żadna rola nie tworzy wejścia ani nie podnosi WAIT. |

## Walidacja

Bramka promocji liczona wyłącznie na części rozwojowej (walidacja), holdout raportowany osobno; kryteria muszą być spełnione, inaczej artefakt ma stan VALIDATION_FAILED i nie może dostać roli ASSIST.

Kontrola potoku na danych SYNTETYCZNYCH (`tools/validate_families_synthetic.py`, profil smoke): **APPROVED**

| Kryterium | Próg | Wartość | Spełnione |
|---|---|---|---|
| converged | > 0.5 | 1 | tak |
| val_qlike_gain_vs_ewma | > 0.0 | 0.0176621 | tak |

## Ograniczenia

* Ocena na danych historycznych nie jest obietnicą wyniku; READY oznacza zdolność zwrócenia wyniku, nie zgodę na handel.
* Model nie składa zleceń; wynik niedostępny (BLOCKED_DATA / STALE / ERROR) nie ma wartości i nie jest traktowany jak neutralny.
* Dane syntetyczne służą wyłącznie do sprawdzenia potoku – rola ASSIST wymaga walidacji na Twoich danych REAL z MT5.
