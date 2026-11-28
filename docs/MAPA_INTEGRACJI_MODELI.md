# Mapa integracji modeli – 1.33.0 (PMW-FAM-1)

Wygenerowane przez `tools/model_docs.py` z katalogu `FamilyService.catalog()`.

Role: OFF = nie liczy; SHADOW = liczy i zapisuje, rola OBSERVE (bez wpływu); ASSIST = tylko po walidacji APPROVED na danych REAL – może wyłącznie wstrzymać wejście (SH: READY→WAIT, ACTIVE: węzeł MODELS); REQUIRED = `config.decision.required_models` – brak / nieświeża / przeciwna prognoza blokuje nowe wejście. Żadna rola nie tworzy wejścia ani nie podnosi WAIT.

Rola ASSIST działa tylko tam, gdzie wynik ma odbiorcę (kolumna ASSIST): HOLD_DIRECTION = wstrzymanie wejścia przy przeciwnym rozkładzie kierunku, CONTEXT_VOL = scenariusz zmienności w widoku ryzyka SH, NONE = rola odrzucana (ASSIST_NO_RECEIVER).

| Rodzina | Nazwa | Zadanie / jednostka | TF / horyzonty | Środowisko | Zależności | Odbiorcy | ASSIST |
|---|---|---|---|---|---|---|---|
| `TS_ARIMA` | ARIMA (statsmodels) – prognoza log-zwrotu | REGRESSION / log_return | M5 / 1, 3, 5 | MAIN | statsmodels, pandas, scipy | SH_CONTEXT:expected_move<br>DECISION:coordinator (REQUIRED / ASSIST – kierunek UP/FLAT/DOWN)<br>PANEL:model_status<br>planowani, niepodłączeni: AGENT:context | NONE |
| `TS_SARIMAX` | SARIMAX (statsmodels) – zwroty H1 z kalendarzem sesji jako exog | REGRESSION / log_return | H1 / 1, 3, 5 | MAIN | statsmodels, pandas, scipy | SH_CONTEXT:expected_move_h1<br>DECISION:coordinator (REQUIRED / ASSIST – kierunek UP/FLAT/DOWN)<br>PANEL:model_status<br>planowani, niepodłączeni: AGENT:context | NONE |
| `VOL_GARCH` | GARCH(1,1) (arch) – zmienność warunkowa | VOLATILITY / sigma_return | M5 / 1, 6, 12 | MAIN | arch, scipy | SH_CONTEXT:volatility<br>PANEL:model_status<br>planowani, niepodłączeni: RISK:volatility_scenario | CONTEXT_VOL |
| `MICROSTRUCTURE` | Mikrostruktura – arkusz brokera (imbalance, OFI, microprice) + klasyfikator reakcji | MICROSTRUCTURE / mixed | – / – | MAIN | sklearn | SH_CONTEXT:entry_quality<br>PANEL:microstructure<br>planowani, niepodłączeni: RISK:execution_conditions | NONE |
| `PAIR_COINT` | Kointegracja pary + z-score (Engle-Granger) | PAIR_RELATION / z_score | H1 / 1 | MAIN | statsmodels | PANEL:pair_relation<br>planowani, niepodłączeni: AGENT:context, PORTFOLIO:basket_proposal (via risk/gateway) | NONE |
| `STATARB` | Arbitraż statystyczny – koszyk PCA + reszty (s-score) | PAIR_RELATION / z_score | H1 / 1 | MAIN | sklearn | PANEL:basket<br>planowani, niepodłączeni: PORTFOLIO:basket_proposal (via risk/gateway) | NONE |
| `KALMAN_LS` | Filtr Kalmana poziom + nachylenie (rozbudowa mm_kalman) | FILTER_STATE / mixed | M5 / 1 | MAIN | – | SH_CONTEXT:trend_state<br>PANEL:model_status<br>planowani, niepodłączeni: STRATEGY:regime_context | NONE |
| `BREAKOUT` | Breakout – wspólny moduł logiki wybicia (kanał, kompresja, potwierdzenie, retest) | FILTER_STATE / mixed | M5 / 1 | MAIN | – | SH_CONTEXT:breakout_state<br>PANEL:model_status<br>planowani, niepodłączeni: STRATEGY:S05/S12 BREAKOUT_RETEST context | NONE |
| `TH_RF` | Random Forest (trainhub) | CLASS_PROBABILITIES / probability | M1, M5, M15, M30 / h świec (per paczka) | MAIN | – | MODELHUB:trainhub_inference -> all_predictions<br>SH_CONTEXT:direction_distribution<br>PANEL:training_center | NONE |
| `TH_XGB` | XGBoost (trainhub, eksport natywny JSON) | CLASS_PROBABILITIES / probability | M1, M5, M15, M30 / h świec (per paczka) | MAIN | xgboost | MODELHUB:trainhub_inference -> all_predictions<br>SH_CONTEXT:direction_distribution<br>PANEL:training_center | NONE |
| `TH_SVM` | SVM (trainhub, kalibracja chronologiczna) | CLASS_PROBABILITIES / probability | M1, M5, M15, M30 / h świec (per paczka) | MAIN | – | MODELHUB:trainhub_inference -> all_predictions<br>SH_CONTEXT:direction_distribution<br>PANEL:training_center | NONE |
| `SEQ_LSTM` | LSTM (PyTorch, .venv_deep) – rozkład kierunku po kosztach | CLASS_PROBABILITIES / probability | M5 / 6 | DEEP | torch | SH_CONTEXT:direction_distribution<br>MODELHUB:direction_group M5<br>PANEL:model_status | HOLD_DIRECTION |
| `SEQ_GRU` | GRU świecowy (PyTorch, .venv_deep) – rozkład kierunku po kosztach | CLASS_PROBABILITIES / probability | M5 / 6 | DEEP | torch | SH_CONTEXT:direction_distribution<br>MODELHUB:direction_group M5<br>PANEL:model_status | HOLD_DIRECTION |
| `RL_PPO` | PPO (Stable-Baselines3, Gymnasium replay) – propozycja ekspozycji | RL_ACTION / action | M5 / – | DEEP | torch, gymnasium, stable_baselines3 | PANEL:model_status<br>planowani, niepodłączeni: RISK:exposure_proposal (OBSERVE) | NONE |
| `NLP_SENTIMENT` | Sentyment tekstu – TF-IDF + regresja logistyczna | NLP_SENTIMENT / sentiment | – / – | MAIN | sklearn | PANEL:news_sentiment<br>planowani, niepodłączeni: AGENT:news_context, RISK:information_context (OBSERVE) | NONE |
| `SEQ_GRU_EVENT` | Event GRU (istniejący mm/event_engine) – adapter | CLASS_PROBABILITIES / probability | EVENT / 2 jednostki zdarzeń (16 zdarzeń/jednostka) | MAIN | – | PANEL:model_status<br>MM_BOARD:evidence | NONE |

## Gdzie prognozy trafiają w działającym bocie

* **SCALPING / HEDGING** – `SHService.evaluate` → `FamilyService.setup_context` (kontekst w setupie, `family_context`) i `apply_to_setup` (ASSIST: READY→WAIT z powodem w checklistcie); koordynator PMW-ARC-1 zapisuje DecisionRecord i stosuje REQUIRED.
* **ACTIVE (S01–S12)** – `engine.light_cycle` → `DecisionCoordinator.model_gate_active` → węzeł `MODELS` drzewa decyzji (przed hashem decyzji), więc karta sygnału i bramka wykonania widzą ten sam werdykt.
* **Panel** – Centrum treningu → „Rodziny modeli 1.33” (`/api/v1/families`, `/api/v1/families/predictions`); Koordynator decyzji (`#/decyzje`).
* **Quant / API** – `modelhub.adapters.all_predictions` (migawka Quant, `/api/v1/models/predictions`, `/api/v1/models/evidence`). Agent nie czyta prognoz rodzin – odbiorcy AGENT / RISK / STRATEGY / PORTFOLIO są tylko planowani (niepodłączeni w 1.46).
* **TH_RF / TH_SVM / TH_XGB** – przez trainhub (Centrum treningu, paczki aktywowane ręcznie); **SEQ_GRU_EVENT** – adapter modelu zdarzeń MM.

