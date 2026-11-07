# Karta modelu – STATARB

**Arbitraż statystyczny – koszyk PCA + reszty (s-score)**

| Pole | Wartość |
|---|---|
| Rodzaj | TRAINED (estymacja czynników + walidacja reszt) |
| Zadanie | BASKET_RESIDUAL_S – typ PMW-PRED-2 `PAIR_RELATION`, jednostka `z_score` |
| Interwał / horyzonty | H1 / 1 |
| Środowisko | MAIN (sklearn) |
| Dane | MULTI_SERIES, H1, ≥ 500 świec |
| Odbiorcy | PANEL:basket, PORTFOLIO:basket_proposal (via risk/gateway) |
| Role | OFF = nie liczy; SHADOW = liczy i zapisuje, rola OBSERVE (bez wpływu); ASSIST = tylko po walidacji APPROVED na danych REAL – może wyłącznie wstrzymać wejście (SH: READY→WAIT, ACTIVE: węzeł MODELS); REQUIRED = `config.decision.required_models` – brak / nieświeża / przeciwna prognoza blokuje nowe wejście. Żadna rola nie tworzy wejścia ani nie podnosi WAIT. |

## Walidacja

Bramka promocji liczona wyłącznie na części rozwojowej (walidacja), holdout raportowany osobno; kryteria muszą być spełnione, inaczej artefakt ma stan VALIDATION_FAILED i nie może dostać roli ASSIST.

Kontrola potoku na danych SYNTETYCZNYCH (`tools/validate_families_synthetic.py`, profil smoke): **APPROVED**

| Kryterium | Próg | Wartość | Spełnione |
|---|---|---|---|
| val_residual_std_ratio | < 2.0 | 1.02081 | tak |

## Ograniczenia

* Ocena na danych historycznych nie jest obietnicą wyniku; READY oznacza zdolność zwrócenia wyniku, nie zgodę na handel.
* Model nie składa zleceń; wynik niedostępny (BLOCKED_DATA / STALE / ERROR) nie ma wartości i nie jest traktowany jak neutralny.
* Dane syntetyczne służą wyłącznie do sprawdzenia potoku – rola ASSIST wymaga walidacji na Twoich danych REAL z MT5.
