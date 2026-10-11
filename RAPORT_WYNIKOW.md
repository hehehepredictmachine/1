# Raport wyników – EMA20 Pullback 2.5R (M30)

Źródło danych: **SYNTHETIC_SIMULATOR (FakeMT5 seed=11) - NIE SĄ TO NOTOWANIA**. Run `20261011T125113Z_SYN`, pliki: `data/results/ema_pullback/20261011T125113Z_SYN`.

> **To są dane syntetyczne z symulatora terminala.** Wynik sprawdza wyłącznie działanie potoku (sygnały, wykonanie, koszty, statystyki). Nie jest dowodem przewagi strategii ani podstawą do decyzji handlowych. Dla dowodu uruchom runner na eksporcie z Twojego terminala (instrukcja niżej).

## Deklaracja z nazwy pliku
Nazwa pliku deklaruje winrate 42,86% i PF 1,52. Plik nie zawiera okresu, instrumentu, kosztów ani liczby transakcji – **wartości nie są zweryfikowane** i nie zostały odtworzone w tym środowisku (brak historii XAUUSD- z Twojego terminala).

## Protokół
```
(fixed BEFORE looking at results):
  1. chronological split: development = first 75% of bars (3 folds), final test = last 25% (evaluated ONCE, frozen config)
  2. variants: ORIGINAL/PINE_DEFAULT (baseline replica), ORIGINAL/MT5 (same signals, realistic execution),
     FIXED/MT5 (bug fixes, same parameters), candidates = FIXED + one hypothesis each (ablation) + all combined
  3. promotion rule (development folds only): candidate expectancy_R > FIXED + 0.05 R, max DD <= 1.2 x FIXED,
     expectancy_R > 0 in >= 2 of 3 folds, >= 30 trades in development; otherwise FIXED stays the configuration
  4. final test once for FIXED and the chosen configuration; stress: costs x2, slippage +3 ticks, entry delay 1 bar,
     neighbouring parameters; moving-block bootstrap 90% intervals; same-bar SL/TP = SL (conservative)
```
Okresy: rozwój 2025-08-18T00:00:00Z – 2026-06-26T22:00:00Z (10349 świec); test końcowy 2026-06-26T22:30:00Z – 2026-10-09T22:00:00Z (3450 świec).

## Etapy na okresie rozwojowym (te same parametry)
| Wariant | Transakcje | Winrate % (bez BE) | BE | PF | E[R] [90% CI] | ROI % | Max DD % | Koszty |
|---|---|---|---|---|---|---|---|---|
| ORIGINAL_PINE_DEFAULT | 154 | 31.17 | 0 | 0.906 | -0.0673 [-0.3055; 0.1077] | -12.16 | 28.96 | 2236.93 |
| ORIGINAL_MT5 | 174 | 31.03 | 0 | 1.061 | 0.0593 [-0.1615; 0.2155] | 8.04 | 21.92 | 202.72 |
| FIXED_MT5 | 167 | 31.74 | 0 | 1.109 | 0.082 [-0.1153; 0.2837] | 12.75 | 13.43 | 200.69 |

## Kandydaci (ablacja, tylko okres rozwojowy)
| Wariant | Transakcje | Winrate % (bez BE) | BE | PF | E[R] [90% CI] | ROI % | Max DD % | Koszty |
|---|---|---|---|---|---|---|---|---|
| C1_ZONE_TOUCH | 177 | 31.07 | 0 | 1.081 | 0.0614 [-0.1231; 0.2515] | 9.87 | 10.72 | 183.89 |
| C2_RECLAIM | 202 | 32.67 | 0 | 1.166 | 0.1282 [-0.046; 0.3021] | 25.13 | 11.51 | 263.76 |
| C3_EMA_SEPARATION | 155 | 28.39 | 0 | 0.941 | -0.0362 [-0.2253; 0.1803] | -6.12 | 14.08 | 166.67 |
| C4_H8_TREND | 92 | 32.61 | 0 | 1.156 | 0.1241 [-0.1045; 0.4306] | 9.9 | 11.31 | 122.71 |
| C5_ALL | 65 | 32.31 | 0 | 1.169 | 0.117 [-0.206; 0.4941] | 7.44 | 10.74 | 69.02 |

Reguła promocji (ustalona przed oceną):
- C1_ZONE_TOUCH: E[R]=0.0614 vs FIXED 0.082, DD 10.72% vs 13.43%, folds>0: 2/3, n=177 -> nie spełnia
- C2_RECLAIM: E[R]=0.1282 vs FIXED 0.082, DD 11.51% vs 13.43%, folds>0: 3/3, n=202 -> nie spełnia
- C3_EMA_SEPARATION: E[R]=-0.0362 vs FIXED 0.082, DD 14.08% vs 13.43%, folds>0: 0/3, n=155 -> nie spełnia
- C4_H8_TREND: E[R]=0.1241 vs FIXED 0.082, DD 11.31% vs 13.43%, folds>0: 2/3, n=92 -> nie spełnia
- C5_ALL: E[R]=0.117 vs FIXED 0.082, DD 10.74% vs 13.43%, folds>0: 2/3, n=65 -> nie spełnia

**Wybrana konfiguracja: FIXED_MT5** (jeśli żaden kandydat nie spełnił reguły – zostaje FIXED; kandydaci pozostają eksperymentalni).

## Test końcowy (oceniony raz)
| Wariant | Transakcje | Winrate % (bez BE) | BE | PF | E[R] [90% CI] | ROI % | Max DD % | Koszty |
|---|---|---|---|---|---|---|---|---|
| FIXED_MT5 | 67 | 38.81 | 0 | 1.551 | 0.3409 [0.0303; 0.7061] | 24.61 | 6.63 | 101.08 |
| ORIGINAL_PINE_DEFAULT | 67 | 38.81 | 0 | 1.186 | 0.1464 [-0.127; 0.502] | 9.27 | 9.29 | 1200.75 |

## Testy obciążeniowe (wybrana konfiguracja, okres testowy)
| Scenariusz | Transakcje | Winrate % | PF | E[R] | ROI % |
|---|---|---|---|---|---|
| COSTS_X2 | 67 | 38.81 | 1.521 | 0.3272 | 23.5 |
| SLIPPAGE_+3 | 67 | 38.81 | 1.541 | 0.3375 | 24.28 |
| ENTRY_DELAY_1 | 59 | 37.29 | 1.413 | 0.289 | 16.02 |
| RR_2.0 | 72 | 41.67 | 1.367 | 0.2333 | 16.05 |
| RR_3.0 | 61 | 32.79 | 1.411 | 0.2935 | 17.74 |
| SWING_8 | 69 | 37.68 | 1.468 | 0.3001 | 21.73 |
| SWING_12 | 62 | 37.1 | 1.399 | 0.2826 | 16.24 |
| ADX_18 | 70 | 37.14 | 1.45 | 0.2828 | 21.08 |
| ADX_22 | 63 | 39.68 | 1.612 | 0.3716 | 25.46 |

## Oryginał vs wersja naprawiona – te same świece
Potwierdzenia oryginału: 1151, wersji naprawionej: 971, zgodne: 961. Rozbieżności oryginału: wbrew trendowi 144, na granicy wygaśnięcia 0, przedłużone ponownym dotknięciem 24, w okresie rozgrzewki 16, inne 6.

Liczba przetestowanych wariantów/scenariuszy: 17 (uwzględnij przy ocenie ryzyka przeuczenia).

## Jak uruchomić na danych z terminala
```
cd backend
..\.venv\Scripts\python.exe -m masterquo export --from-utc 2025-01-01T00:00:00Z --to-utc 2026-06-01T00:00:00Z --out ..\data\export_xau
cd ..
.venv\Scripts\python.exe tools\backtest_ema_pullback.py --csv data\export_xau --tf M30 --commission-lot-side <prowizja z terminala>
```
Definicje: winrate = wygrane/(wygrane+przegrane) po kosztach, BE (|R| ≤ 0,05) osobno; PF = suma zysków netto / |suma strat netto| (brak strat = „brak strat”, nie nieskończoność); E[R] = średni wynik netto w R; ROI = wynik netto / kapitał początkowy w okresie; max DD z krzywej kapitału wycenianej na zamknięciach świec.
