# Karta modelu – SEQ_LSTM

**LSTM (PyTorch, .venv_deep) – rozkład kierunku po kosztach**

| Pole | Wartość |
|---|---|
| Rodzaj | TRAINED (trening) |
| Zadanie | DIRECTION_H6_AFTER_COST – typ PMW-PRED-2 `CLASS_PROBABILITIES`, jednostka `probability` |
| Interwał / horyzonty | M5 / 6 |
| Środowisko | DEEP (torch) |
| Dane | BARS, M5, ≥ 3000 świec, BAR_SEQ_V1 |
| Odbiorcy | SH_CONTEXT:direction_distribution, MODELHUB:direction_group M5, PANEL:model_status |
| Role | OFF = nie liczy; SHADOW = liczy i zapisuje, rola OBSERVE (bez wpływu); ASSIST = tylko po walidacji APPROVED na danych REAL – może wyłącznie wstrzymać wejście (SH: READY→WAIT, ACTIVE: węzeł MODELS); REQUIRED = `config.decision.required_models` – brak / nieświeża / przeciwna prognoza blokuje nowe wejście. Żadna rola nie tworzy wejścia ani nie podnosi WAIT. |

## Walidacja

Bramka promocji liczona wyłącznie na części rozwojowej (walidacja), holdout raportowany osobno; kryteria muszą być spełnione, inaczej artefakt ma stan VALIDATION_FAILED i nie może dostać roli ASSIST.

Kontrola potoku na danych SYNTETYCZNYCH (`tools/validate_families_synthetic.py`, profil smoke): **VALIDATION_FAILED**

| Kryterium | Próg | Wartość | Spełnione |
|---|---|---|---|
| val_skill | > 0.0 | -0.185353 | nie |
| param_change_l1 | > 0.0 | 17.2944 | tak |

## Ograniczenia

* Ocena na danych historycznych nie jest obietnicą wyniku; READY oznacza zdolność zwrócenia wyniku, nie zgodę na handel.
* Model nie składa zleceń; wynik niedostępny (BLOCKED_DATA / STALE / ERROR) nie ma wartości i nie jest traktowany jak neutralny.
* Dane syntetyczne służą wyłącznie do sprawdzenia potoku – rola ASSIST wymaga walidacji na Twoich danych REAL z MT5.
