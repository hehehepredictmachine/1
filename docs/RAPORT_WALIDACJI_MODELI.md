# Raport walidacji modeli – 1.33.0

Źródło: `docs/RAPORT_WALIDACJI_MODELI.json` – `tools/validate_families_synthetic.py` (profil **smoke**, dane **SYNTHETIC**, 2026-11-07T19:34:06Z, Python 3.13.18, Linux-6.18.44-fc-v310-x86_64-with-glibc2.39).

**Co to sprawdza:** dane syntetyczne o znanej strukturze – sprawdzenie potoku trening→zapis→ładowanie→predykcja i bramki walidacji, nie rentowności. Każda rodzina: trening → zapis (manifest + sumy) → ładowanie → predykcja zgodna z PMW-PRED-2 → bramka walidacji. Dane mają znaną strukturę (AR(1)+GARCH, para kointegrowana, koszyk 3 serii, arkusz z nierównowagą wyprzedzającą mid, oznaczony korpus nagłówków).

**Czego nie sprawdza:** rentowności ani jakości na rzeczywistym XAUUSD/BTC – tego nie da się zrobić bez Twoich danych MT5. Przed rolą ASSIST każdą rodzinę trzeba wytrenować i zwalidować na danych REAL (Centrum treningu lub Studio).

| Rodzina | Wynik treningu | Bramka | Kluczowe kryteria (walidacja) | Predykcja PMW-PRED-2 | Czas |
|---|---|---|---|---|---|
| `TS_ARIMA` | DONE | APPROVED | converged 1 > 0.5; stable 1 > 0.5; val_skill_vs_zero 0.0359 > 0.0 | READY | 1.2 s |
| `TS_SARIMAX` | DONE | APPROVED | converged 1 > 0.5; val_skill_vs_zero 0.0237 > 0.0 | READY | 0.7 s |
| `VOL_GARCH` | DONE | APPROVED | converged 1 > 0.5; val_qlike_gain_vs_ewma 0.0177 > 0.0 | READY | 0.1 s |
| `MICROSTRUCTURE` | DONE | APPROVED | val_skill 0.0368 > 0.0 | READY | 0.1 s |
| `PAIR_COINT` | DONE | APPROVED | p_value_train 0 < 0.05; val_std_ratio 0.916 < 2.0; sd_train 0.00311 > 1e-09 | READY | 0.0 s |
| `STATARB` | DONE | APPROVED | val_residual_std_ratio 1.02 < 2.0 | READY | 0.1 s |
| `KALMAN_LS` | DONE | APPROVED | z_std_ok 1 > 0.5 | READY | 1.2 s |
| `BREAKOUT` | DONE | APPROVED | dev_expectancy_after_cost 0.594 > 0.0; dev_trades 24 > 19.0 | READY | 0.1 s |
| `TH_RF` | DELEGATED | – | trainhub (test_trainhub) / centrum MM | – | 0 s |
| `TH_XGB` | DELEGATED | – | trainhub (test_trainhub) / centrum MM | – | 0 s |
| `TH_SVM` | DELEGATED | – | trainhub (test_trainhub) / centrum MM | – | 0 s |
| `SEQ_LSTM` | DONE | VALIDATION_FAILED | val_skill -0.185 > 0.0; param_change_l1 17.3 > 0.0 | READY | 3.9 s |
| `SEQ_GRU` | DONE | VALIDATION_FAILED | val_skill -0.183 > 0.0; param_change_l1 12.3 > 0.0 | READY | 2.8 s |
| `RL_PPO` | DONE | VALIDATION_FAILED | val_ppo_minus_flat -20.5 > 0.0; val_ppo_minus_momentum -129 > 0.0 | READY | 3.3 s |
| `NLP_SENTIMENT` | DONE | APPROVED | val_skill 1 > 0.0 | READY | 0.0 s |
| `SEQ_GRU_EVENT` | DELEGATED | – | trainhub (test_trainhub) / centrum MM | – | 0 s |

## Wnioski

* Rodziny statystyczne i regułowe (ARIMA, SARIMAX, GARCH, Kalman, breakout, para, koszyk, mikrostruktura, NLP) przechodzą bramkę na danych o znanej strukturze – potok i kryteria działają.
* **SEQ_LSTM, SEQ_GRU, RL_PPO przy profilu smoke nie przechodzą bramki** (ujemny zysk walidacyjny względem odniesienia). To zamierzone zachowanie bramki: budżet smoke (kilka epok / kroków) sprawdza tylko, że trening naprawdę zmienia parametry i że artefakt się ładuje; do oceny służą profile research / full na danych REAL. Artefakt VALIDATION_FAILED nie może dostać roli ASSIST.
* **Naprawione w trakcie (audyt 1.33):** SARIMAX na H1 z grupowaniem zmienności nie zbiegał w żadnym dopasowaniu (stan BLOCKED). Przyczyna: surowe log-zwroty rzędu 1e-3 psuły skalowanie optymalizatora MLE. Poprawka: dopasowanie na zwrotach skalowanych do wariancji 1, skala zapisana w artefakcie, prognozy i błędy w jednostkach log-zwrotu; stare artefakty bez skali działają jak dotąd (skala 1). Test: `test_families_u4.test_sarimax_converges_on_h1_with_volatility_clustering`.
* TH_RF / TH_SVM / TH_XGB – walidowane w `tests/test_trainhub.py` (22 testy); SEQ_GRU_EVENT – centrum MM (`test_mm_*`).
