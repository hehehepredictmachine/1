# Postęp wdrożenia modeli (AUD) – 1.33.0

Wszystkie 15 rodzin ma stan „zaimplementowane i podłączone”. Rola domyślna każdej to OFF; MICROSTRUCTURE liczy pomiary w SHADOW.
Wynik walidacji kontrolnej na danych syntetycznych (smoke) pochodzi z `docs/RAPORT_WALIDACJI_MODELI.md`.

| Rodzina | Kod | Trening | Inferencja w bocie | Odbiorcy | Walidacja kontrolna (SYNTHETIC, smoke) | Testy |
|---|---|---|---|---|---|---|
| TS_ARIMA | `families/arima.py` | główne środowisko | FamilyService | SH kontekst, panel, agent | APPROVED | `test_families_u4` |
| TS_SARIMAX | `families/arima.py` | główne | FamilyService | SH kontekst H1 | APPROVED (po naprawie A8) | `test_families_u4` |
| VOL_GARCH | `families/garch.py` | główne (`arch`) | FamilyService | SH zmienność, ryzyko | APPROVED | `test_families_u4` |
| MICROSTRUCTURE | `families/micro.py` | główne | pomiary bez modelu + klasyfikator | SH jakość wejścia | APPROVED | `test_families_u4`, `test_indicators_u2` |
| PAIR_COINT | `families/pairs.py` | główne | wymaga `families.pairs` | SH kontekst pary | APPROVED | `test_families_u4` |
| STATARB | `families/pairs.py` | główne | wymaga `families.basket` (≥3) | panel | APPROVED | `test_families_u4` |
| KALMAN_LS | `families/kalman_ls.py` | główne | FamilyService | SH trend lokalny | APPROVED | `test_families_u4` |
| BREAKOUT | `families/breakout.py` | główne (reguły + walidacja parametrów po kosztach) | FamilyService | SH | APPROVED | `test_families_u4` |
| TH_RF | `trainhub/learn.py` | trainhub | trainhub_inference | SH / panel | `test_trainhub` | `test_trainhub` |
| TH_SVM | `trainhub/learn.py` | trainhub (kalibracja) | trainhub_inference | SH / panel | `test_trainhub` | `test_trainhub` |
| TH_XGB | `trainhub/learn.py` | trainhub (natywny JSON) | trainhub_inference | SH / panel | `test_trainhub` | `test_trainhub` |
| SEQ_LSTM | `families/seq.py` + `deep_runtime/seq.py` | `.venv_deep` | worker deep | SH rozkład kierunku | VALIDATION_FAILED (smoke – zamierzone, patrz raport) | `test_families_u4` (rzeczywisty trening torch) |
| SEQ_GRU | jak wyżej | `.venv_deep` | worker deep | SH | VALIDATION_FAILED (smoke) | `test_families_u4` |
| RL_PPO | `families/rl.py`, `rl_core.py` + `deep_runtime/rl.py` | `.venv_deep` (SB3) | propozycja akcji | panel / SH kontekst | VALIDATION_FAILED (smoke) | `test_families_u4` |
| NLP_SENTIMENT | `families/nlp.py` | główne (TF-IDF + kalibracja) / lokalny transformer | FamilyService | SH kontekst, agent | APPROVED | `test_families_u4` |
| (adapter) SEQ_GRU_EVENT | `families/seq.py` → MM | centrum MM | mm | SH | `test_mm_*` | `test_families_u4` |
