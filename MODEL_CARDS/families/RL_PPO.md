# Karta modelu – RL_PPO

**PPO (Stable-Baselines3, Gymnasium replay) – propozycja ekspozycji**

| Pole | Wartość |
|---|---|
| Rodzaj | TRAINED (trening) |
| Zadanie | TARGET_EXPOSURE – typ PMW-PRED-2 `RL_ACTION`, jednostka `action` |
| Interwał / horyzonty | M5 / brak (pomiar stanu) |
| Środowisko | DEEP (torch, gymnasium, stable_baselines3) |
| Dane | BARS, M5, ≥ 3000 świec |
| Odbiorcy | PANEL:model_status |
| Odbiorcy planowani | RISK:exposure_proposal (OBSERVE) – niepodłączeni w 1.46 (brak odbiorcy w kodzie) |
| Role | OFF = nie liczy; SHADOW = liczy i zapisuje, rola OBSERVE (bez wpływu); ASSIST = niedostępna – typ wyniku `RL_ACTION` nie ma odbiorcy roli ASSIST (odmowa ASSIST_NO_RECEIVER); wynik działa tylko jako obserwacja; REQUIRED = `config.decision.required_models` – brak / nieświeża / przeciwna prognoza blokuje nowe wejście. Żadna rola nie tworzy wejścia ani nie podnosi WAIT. |

## Walidacja

Bramka promocji liczona wyłącznie na części rozwojowej (walidacja), holdout raportowany osobno; kryteria muszą być spełnione, inaczej artefakt ma stan VALIDATION_FAILED i nie może dostać roli ASSIST.

Kontrola potoku na danych SYNTETYCZNYCH (`tools/validate_families_synthetic.py`, profil smoke): **VALIDATION_FAILED**

| Kryterium | Próg | Wartość | Spełnione |
|---|---|---|---|
| val_ppo_minus_flat | > 0.0 | -20.466 | nie |
| val_ppo_minus_momentum | > 0.0 | -128.893 | nie |

## Ograniczenia

* Ocena na danych historycznych nie jest obietnicą wyniku; READY oznacza zdolność zwrócenia wyniku, nie zgodę na handel.
* Model nie składa zleceń; wynik niedostępny (BLOCKED_DATA / STALE / ERROR) nie ma wartości i nie jest traktowany jak neutralny.
* Dane syntetyczne służą wyłącznie do sprawdzenia potoku – rola ASSIST wymaga walidacji na Twoich danych REAL z MT5.
