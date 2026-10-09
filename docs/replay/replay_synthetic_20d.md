# Replay S01–S10 – SYNTHETIC

Kroki: 2300 × M15 (575.0 h obserwowanego rynku), 93.9 ms/krok. Metoda: closed-bar replay, next-M5-open entry, SL-first on ambiguous bars, costs in R; DEV/VAL/OOS 60/20/20.
Status: **FUNCTIONAL_REPLAY_SYNTHETIC - wyniki nie są dowodem skuteczności**

| Strategia | Unikalne setupy | /h | EARLY→CONF | Mediana [min] | Transakcje | Expectancy R | PF | Win | DD R | OOS trans. | OOS exp. R |
|---|---|---|---|---|---|---|---|---|---|---|---|
| S01 | 410 | 0.713 | 12 | 30.0 | 36 | 0.681 | 2.99 | 24/36 (67%) | 3.92 | 9 | 0.652 |
| S02 | 130 | 0.226 | 0 | None | 95 | 0.223 | 1.44 | 48/95 (51%) | 7.13 | 23 | -0.031 |
| S03 | 1369 | 2.381 | 0 | None | 428 | 0.267 | 1.56 | 230/428 (54%) | 16.21 | 96 | 0.297 |
| S04 | 140 | 0.243 | 7 | 15.0 | 41 | 0.188 | 1.49 | 26/41 (63%) | 3.33 | 11 | 0.246 |
| S05 | 76 | 0.132 | 1 | 30.0 | 8 | 0.219 | 1.43 | 4/8 (50%) | 3.09 | 1 | 1.634 |
| S06 | 578 | 1.005 | 67 | 15.0 | 132 | 0.229 | 1.48 | 67/132 (51%) | 15.7 | 32 | 0.474 |
| S07 | 1044 | 1.816 | 7 | 15.0 | 176 | 0.048 | 1.08 | 71/176 (40%) | 13.55 | 37 | -0.303 |
| S08 | 418 | 0.727 | 10 | 15.0 | 80 | 0.059 | 1.12 | 42/80 (52%) | 6.78 | 12 | -0.275 |
| S09 | 275 | 0.478 | 5 | 15.0 | 59 | -0.28 | 0.46 | 27/59 (46%) | 17.11 | 16 | -0.465 |
| S10 | 1308 | 2.275 | 11 | 15.0 | 26 | -0.243 | 0.55 | 10/26 (38%) | 9.01 | 5 | -1.025 |

Portfel (tylko wybór AUTO, 1 pozycja naraz): {"trades": 168, "expectancy_r": 0.276, "total_r": 46.34, "profit_factor": 1.6, "win_rate": "92/168 (55%)", "max_drawdown_r": 7.76, "avg_mae_r": 0.81, "avg_mfe_r": 1.36, "avg_hold_m5_bars": 34.1}
Zdarzenia opisane przez kilka strategii jednocześnie: 710 (maks. 4 strategie/zdarzenie).
Zmiany wyboru AUTO: 1172 – przyczyny: {"FIRST_SELECTION": 1, "PREVIOUS_SETUP_NO_LONGER_VALID": 1024, "NEW_CANDIDATE": 115, "CHALLENGER_LEADS": 32}. Reżimy: {"COMPRESSION": 214, "EXPANSION": 60, "TRANSITION": 1067, "TREND_UP": 297, "EXHAUSTION_OR_REVERSAL_CANDIDATE": 152, "RANGE": 177, "TREND_DOWN": 333}

## ORIGINAL (M07) na tych samych danych
{
 "STRICT_H4_H1": {
  "steps": 575,
  "hours_with_direction": 34,
  "unique_plans": 12,
  "per_observed_hour": 0.021
 },
 "H1_LEAD": {
  "steps": 575,
  "hours_with_direction": 171,
  "unique_plans": 59,
  "per_observed_hour": 0.103
 }
}
