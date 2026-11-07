# Mapa integracji modeli – 1.33.0 (PMW-FAM-1)

Wygenerowane przez `tools/model_docs.py` z katalogu `FamilyService.catalog()`.

Role: OFF = nie liczy; SHADOW = liczy i zapisuje, rola OBSERVE (bez wpływu); ASSIST = tylko po walidacji APPROVED na danych REAL – może wyłącznie wstrzymać wejście (SH: READY→WAIT, ACTIVE: węzeł MODELS); REQUIRED = `config.decision.required_models` – brak / nieświeża / przeciwna prognoza blokuje nowe wejście. Żadna rola nie tworzy wejścia ani nie podnosi WAIT.

| Rodzina | Nazwa | Zadanie / jednostka | TF / horyzonty | Środowisko | Zależności | Odbiorcy |
|---|---|---|---|---|---|---|
| `TS_ARIMA` | ARIMA (statsmodels) – prognoza log-zwrotu | REGRESSION / log_return | M5 / 1, 3, 5 | MAIN | statsmodels, pandas, scipy | SH_CONTEXT:expected_move<br>PANEL:model_status<br>AGENT:context |
| `TS_SARIMAX` | SARIMAX (statsmodels) – zwroty H1 z kalendarzem sesji jako exog | REGRESSION / log_return | H1 / 1, 3, 5 | MAIN | statsmodels, pandas, scipy | SH_CONTEXT:expected_move_h1<br>PANEL:model_status<br>AGENT:context |
| `VOL_GARCH` | GARCH(1,1) (arch) – zmienność warunkowa | VOLATILITY / sigma_return | M5 / 1, 6, 12 | MAIN | arch, scipy | RISK:volatility_scenario<br>SH_CONTEXT:volatility<br>PANEL:model_status |
| `MICROSTRUCTURE` | Mikrostruktura – arkusz brokera (imbalance, OFI, microprice) + klasyfikator reakcji | MICROSTRUCTURE / mixed | – / – | MAIN | sklearn | SH_CONTEXT:entry_quality<br>RISK:execution_conditions<br>PANEL:microstructure |
| `PAIR_COINT` | Kointegracja pary + z-score (Engle-Granger) | PAIR_RELATION / z_score | H1 / 1 | MAIN | statsmodels | PANEL:pair_relation<br>AGENT:context<br>PORTFOLIO:basket_proposal (via risk/gateway) |
| `STATARB` | Arbitraż statystyczny – koszyk PCA + reszty (s-score) | PAIR_RELATION / z_score | H1 / 1 | MAIN | sklearn | PANEL:basket<br>PORTFOLIO:basket_proposal (via risk/gateway) |
| `KALMAN_LS` | Filtr Kalmana poziom + nachylenie (rozbudowa mm_kalman) | FILTER_STATE / mixed | M5 / 1 | MAIN | – | SH_CONTEXT:trend_state<br>STRATEGY:regime_context<br>PANEL:model_status |
| `BREAKOUT` | Breakout – wspólny moduł logiki wybicia (kanał, kompresja, potwierdzenie, retest) | FILTER_STATE / mixed | M5 / 1 | MAIN | – | SH_CONTEXT:breakout_state<br>STRATEGY:S05/S12 BREAKOUT_RETEST context<br>PANEL:model_status |
| `TH_RF` | Random Forest (trainhub) | CLASS_PROBABILITIES / probability | M5 / 6 | MAIN | – | MODELHUB:trainhub_inference -> all_predictions<br>SH_CONTEXT:direction_distribution<br>PANEL:training_center |
| `TH_XGB` | XGBoost (trainhub, eksport natywny JSON) | CLASS_PROBABILITIES / probability | M5 / 6 | MAIN | – | MODELHUB:trainhub_inference -> all_predictions<br>SH_CONTEXT:direction_distribution<br>PANEL:training_center |
| `TH_SVM` | SVM (trainhub, kalibracja chronologiczna) | CLASS_PROBABILITIES / probability | M5 / 6 | MAIN | – | MODELHUB:trainhub_inference -> all_predictions<br>SH_CONTEXT:direction_distribution<br>PANEL:training_center |
| `SEQ_LSTM` | LSTM (PyTorch, .venv_deep) – rozkład kierunku po kosztach | CLASS_PROBABILITIES / probability | M5 / 6 | DEEP | torch | SH_CONTEXT:direction_distribution<br>MODELHUB:direction_group M5<br>PANEL:model_status |
| `SEQ_GRU` | GRU świecowy (PyTorch, .venv_deep) – rozkład kierunku po kosztach | CLASS_PROBABILITIES / probability | M5 / 6 | DEEP | torch | SH_CONTEXT:direction_distribution<br>MODELHUB:direction_group M5<br>PANEL:model_status |
| `RL_PPO` | PPO (Stable-Baselines3, Gymnasium replay) – propozycja ekspozycji | RL_ACTION / action | M5 / – | DEEP | torch, gymnasium, stable_baselines3 | RISK:exposure_proposal (OBSERVE)<br>PANEL:model_status |
| `NLP_SENTIMENT` | Sentyment tekstu – TF-IDF + regresja logistyczna (+ opcjonalny lokalny transformer) | NLP_SENTIMENT / sentiment | – / – | MAIN | sklearn | AGENT:news_context<br>PANEL:news_sentiment<br>RISK:information_context (OBSERVE) |
| `SEQ_GRU_EVENT` | Event GRU (istniejący mm/event_engine) – adapter | CLASS_PROBABILITIES / probability | EVENT / 1 | MAIN | – | PANEL:model_status<br>MM_BOARD:evidence |

## Gdzie prognozy trafiają w działającym bocie

* **SCALPING / HEDGING** – `SHService.evaluate` → `FamilyService.setup_context` (kontekst w setupie, `family_context`) i `apply_to_setup` (ASSIST: READY→WAIT z powodem w checklistcie); koordynator PMW-ARC-1 zapisuje DecisionRecord i stosuje REQUIRED.
* **ACTIVE (S01–S12)** – `engine.light_cycle` → `DecisionCoordinator.model_gate_active` → węzeł `MODELS` drzewa decyzji (przed hashem decyzji), więc karta sygnału i bramka wykonania widzą ten sam werdykt.
* **Panel** – Centrum treningu → „Rodziny modeli 1.33” (`/api/v1/families`, `/api/v1/families/predictions`); Koordynator decyzji (`#/decyzje`).
* **Agent** – `modelhub.adapters.all_predictions` (kontekst rozmowy, zamrożony snapshot).
* **TH_RF / TH_SVM / TH_XGB** – przez trainhub (Centrum treningu, paczki aktywowane ręcznie); **SEQ_GRU_EVENT** – adapter modelu zdarzeń MM.

