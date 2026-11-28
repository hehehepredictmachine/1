# Mapa modeli i treningu (XAUUSD / BTC)

Wygenerowano przez `tools/model_map.py` (to samo źródło co `MAPA_MODELI_I_TRENINGU.json`) z rejestru kanonicznego `quant/inventory.build()` – te same identyfikatory i aliasy co `docs/quant/INVENTORY.md` (`backend/masterquo/quant/ids.py`). TF i horyzont pochodzą z rejestru; teksty opisowe (zadanie, dane, etykieta, trainer) z `tools/model_map.ELEMENTS`.
Status opisuje stan KODU w tej paczce. Nie mówi nic o jakości modelu na Twoich danych – tę pokazuje dopiero raport runu treningu.
Jednostka modelu: instrument × zadanie × TF × horyzont × strona. Każdy instrument ma osobne dane, skalery, kalibratory, modele i rejestry.

## rule:data_quality – Jakość i świeżość danych (bridge, zegar, spread)

- **Aliasy:** data_quality
- **Kategoria:** RULE_OR_MEASUREMENT (rejestr: sh.models.REGISTRY)
- **Implementacja:** backend/masterquo/sh/context.py, backend/masterquo/data/quality.py, backend/masterquo/quant/snapshot.py, backend/masterquo/mt5/bridge.py
- **Zadanie:** STATE / state
- **Źródło danych:** notowanie MT5, zegar, spread
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** —
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: GATE_EXISTING

## rule:risk_engine – Wspólny silnik ryzyka SH (limity, margin, spread, ekspozycja)

- **Aliasy:** risk_engine
- **Kategoria:** RULE_OR_MEASUREMENT (rejestr: sh.models.REGISTRY)
- **Implementacja:** backend/masterquo/sh/risk.py, backend/masterquo/risk/portfolio.py
- **Zadanie:** STATE / state
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** —
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: GATE_EXISTING (bramka ryzyka liczona w ścieżce wykonania (RiskBook / risk/portfolio.py) – Quant jej nie dubluje)

## rule:news – Kalendarz makro (blokada wysokiego wpływu)

- **Aliasy:** news
- **Kategoria:** RULE_OR_MEASUREMENT (rejestr: sh.models.REGISTRY)
- **Implementacja:** backend/masterquo/news/
- **Zadanie:** STATE / state
- **Źródło danych:** kalendarz makro (czas pierwszego odbioru)
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** —
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: GATE_EXISTING

## rule:regime_v2 – Reżim rynku MQ_REGIME_MULTI_V2 (market_v2)

- **Aliasy:** regime_v2
- **Kategoria:** RULE_OR_MEASUREMENT (rejestr: sh.models.REGISTRY)
- **Implementacja:** —
- **Zadanie:** STATE / state
- **Źródło danych:** —
- **TF:** M5, M15, H1
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** —
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: CONTEXT_FEATURE

## rule:structure_v2 – Struktura rynku structure_v2 (M5/M15/H1, BOS/CHoCH)

- **Aliasy:** structure_v2
- **Kategoria:** RULE_OR_MEASUREMENT (rejestr: sh.models.REGISTRY)
- **Implementacja:** —
- **Zadanie:** STATE / state
- **Źródło danych:** —
- **TF:** M5, M15, H1
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** —
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: CONTEXT_STATE (rekord STATE w migawce Quant (panel / agent / REQUIRED); quant/features.py nie buduje z niego cech – struktura nie jest wejściem MetaModelu (nowa cecha = osobna decyzja z nową wersją schematu cech))

## rule:smc_pullback – Pullback + SMC (BoS/CHoCH/IDM) – context_ind

- **Aliasy:** smc_pullback
- **Kategoria:** RULE_OR_MEASUREMENT (rejestr: sh.models.REGISTRY)
- **Implementacja:** —
- **Zadanie:** —
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** —
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: CONTEXT_FEATURE (akcesor istnieje: migawka SH sh.snapshot['ctx'] w każdym cyklu SH (smc_trend_m5, smc_high_m5 / smc_low_m5, pb_last_high_m5 / pb_last_low_m5, smc_trend_m1 / smc_last_m1); brak adaptera Quant – nie jest cechą MetaModelu (PMW-PRED-2))

## rule:vamd – VAMD momentum – profil DEFAULT (stały dla SH; kalibracja context_ind dotyczy panelu/badań)

- **Aliasy:** vamd
- **Kategoria:** RULE_OR_MEASUREMENT (rejestr: sh.models.REGISTRY)
- **Implementacja:** —
- **Zadanie:** —
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** —
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: CONTEXT_FEATURE (VAMD liczony na żywo w migawce SH (sh.context: ctx.vamd_m5 / ctx.vamd_m1) i per wykres w context_ind (panel); bez adaptera Quant (PMW-PRED-2) – nie jest modelem „Quant Ultimate Momentum Pro”)

## rule:fractal – Bounded Katz FD (trend/chop bez kierunku) – profil DEFAULT (stały dla SH; kalibracja context_ind dotyczy panelu/badań)

- **Aliasy:** fractal
- **Kategoria:** RULE_OR_MEASUREMENT (rejestr: sh.models.REGISTRY)
- **Implementacja:** —
- **Zadanie:** —
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** —
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: CONTEXT_FEATURE (Katz FD liczony na żywo w migawce SH (sh.context: ctx.fd_zone_m5) i per wykres w context_ind; bez adaptera Quant (PMW-PRED-2))

## rule:atr_vol – Zmienność ATR(14) M1/M5 (sh/context, Wilder)

- **Aliasy:** atr_vol
- **Kategoria:** RULE_OR_MEASUREMENT (rejestr: sh.models.REGISTRY)
- **Implementacja:** —
- **Zadanie:** STATE / price
- **Źródło danych:** —
- **TF:** M1, M5
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** —
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: CONTEXT_FEATURE

## rule:candles_patterns – Świece i formacje (candles, chart_patterns, sci2)

- **Aliasy:** candles_patterns
- **Kategoria:** RULE_OR_MEASUREMENT (rejestr: sh.models.REGISTRY)
- **Implementacja:** —
- **Zadanie:** —
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** —
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: CONTEXT_FEATURE (formacje opisowe (role świec) – kontekst panelu, bez liczbowego wyjścia)

## rule:liquidity – Płynność: sesje (sweep boxes) + heatmapa likwidacji

- **Aliasy:** liquidity
- **Kategoria:** RULE_OR_MEASUREMENT (rejestr: sh.models.REGISTRY)
- **Implementacja:** —
- **Zadanie:** —
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** —
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: CONTEXT_FEATURE (poziomy płynności (boksy sesji / sweep – analytics.session_engine, heatmapa likwidacji – analytics.liquidation) w polityce OBSERVE analytics.liquidity_context (panel, kontekst silnika, agent); brak adaptera Quant i brak cechy MetaModelu)

## rule:flow_sr – Heikin Flow + kanały S/R (flow_context)

- **Aliasy:** flow_sr
- **Kategoria:** RULE_OR_MEASUREMENT (rejestr: sh.models.REGISTRY)
- **Implementacja:** —
- **Zadanie:** —
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** —
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: CONTEXT_FEATURE (pasma S/R flow_context per wykres – bez akcesora snapshotu)

## rule:decomposition – Wskaźniki, FFT/VMD/EMD, BB/MA, Double Bottom

- **Aliasy:** decomposition, INDICATORS_FFT_VMD_EMD
- **Kategoria:** RULE_OR_MEASUREMENT (rejestr: sh.models.REGISTRY)
- **Implementacja:** masterquo/analytics/*, indicators/series.py
- **Zadanie:** obliczenia – nie są sieciami i nie mają przycisku „trenuj”
- **Źródło danych:** bary bota
- **TF:** różne
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** brak
- **Loader:** AnalyticsService
- **Artefakt:** —
- **Instrumenty:** XAUUSD, BTC
- **Status:** kod: IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: CONTEXT_FEATURE (obserwacja cyklu (FFT/EMD/VMD) – brak zadania predykcyjnego) | opis: OBLICZENIA

## sh:tp_model – SH: P(TP2 przed SL w horyzoncie) – model zdarzenia strategii

- **Aliasy:** sh_tp_model
- **Kategoria:** MODEL_TRAINED (rejestr: sh.models.REGISTRY)
- **Implementacja:** backend/masterquo/sh/tpmodel.py
- **Zadanie:** EVENT_PROBABILITY / TP2_BEFORE_SL_H / probability
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** training (sh_models)
- **Loader:** sh.service
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: SETUP_EVENT

## scalp:A_direction – Scalp A – kierunek 1/3/5 min (BASELINE, LR, HGB, MLP 64-32, kwantyle HGB)

- **Aliasy:** scalp_A, SCALP_A
- **Kategoria:** MODEL_TRAINED (rejestr: sh.models.REGISTRY)
- **Implementacja:** gold_candles_runtime/scalp_train.py, scalp_features.py, scalp_infer.py
- **Zadanie:** klasa DOWN/FLAT/UP po kosztach (tau = max(0.2×ATR, koszt))
- **Źródło danych:** eksport M1 (+M5…H1 dla kontekstu replayu)
- **TF:** M1
- **Horyzont:** 1/3/5 min
- **Strona:** oba (klasy)
- **Cechy:** SCALP-FEAT-1.0.0 (zwroty, ATR, świeca, BB, SAR, wolumen, spread, sesja)
- **Etykieta:** zmiana ceny względem progu kosztowego
- **Trainer:** gold_candles_runtime.scalp_train --instrument (walk-forward 5 bloków, embargo, kalibracja, holdout)
- **Loader:** scalp_infer.ScalpModel przez worker (cmd scalp_forecast)
- **Artefakt:** data/scalp/runs/<run> (XAUUSD) | data/instruments/BTC/scalp/runs/<run>; registry.json per instrument
- **Instrumenty:** XAUUSD, BTC
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: BASE_FORECAST | opis: ZAIMPLEMENTOWANE_I_ZINTEGROWANE; profil BTC = kopia reguł XAUUSD (wszystkie progi względne) jako hipoteza

## scalp:B_setup_quality – Scalp B – jakość setupu P(TP1 przed SL) (LR, HGB)

- **Aliasy:** scalp_B, SCALP_B
- **Kategoria:** MODEL_TRAINED (rejestr: sh.models.REGISTRY)
- **Implementacja:** gold_candles_runtime/scalp_train.py train_setup_model
- **Zadanie:** P(TP1 przed SL) cyklu Range→Sweep→Retest
- **Źródło danych:** cykle z replayu profilu scalp na eksporcie
- **TF:** M1
- **Horyzont:** do 30 min (max_hold)
- **Strona:** BUY i SELL (cecha kierunku)
- **Cechy:** cechy cyklu z replayu
- **Etykieta:** tp1_before_sl
- **Trainer:** scalp_train (te same bloki czasowe)
- **Loader:** scalp_infer.SetupModel (worker setup_quality)
- **Artefakt:** jak Scalp A
- **Instrumenty:** XAUUSD, BTC
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: SETUP_EVENT (P(TP1 przed SL) INNEGO setupu (Range→Sweep→Retest) – liczony tylko dla planu scalp; brak modelu z replayu na danych rzeczywistych) | opis: ZAIMPLEMENTOWANE; zwykle BRAK_PRZESLANEK przy małej liczbie cykli

## forecast:gold_candles – Prognozy świec (gold_candles) – regresja logistyczna wieloklasowa + kalibracja + kwantyle GBR

- **Aliasy:** gold_candles, gold_candles_15m, gold_candles_30m, gold_candles_5m, gold_forecast, FORECAST_GOLD_CANDLES
- **Kategoria:** MODEL_TRAINED (rejestr: sh.models.REGISTRY)
- **Implementacja:** backend/gold_candles/model.py, gold_candles_runtime/plan_train.py
- **Zadanie:** rozkład kierunku zamknięcia DOWN/FLAT/UP (próg ±0.20×ATR) + kwantyle q10/q50/q90
- **Źródło danych:** eksport MT5 M5 + M30 dokładnego symbolu (czas serwera → UTC, zmierzony offset / NY_CLOSE)
- **TF:** M5
- **Horyzont:** 1/3/6 świec M5 (5/15/30 min)
- **Strona:** nie dotyczy (rozkład)
- **Cechy:** gold_candles/features.py (wzorce świec, ATR, pozycja w siatce grid_step z profilu instrumentu, kontekst M30)
- **Etykieta:** klasa zmiany ceny zamknięcia po h świecach względem ATR
- **Trainer:** gold_candles_runtime.plan_train (.venv_candles; plan zamrożony, fit/kalibracja/holdout chronologicznie)
- **Loader:** gold_candles_runtime.worker → gold_candles.model.forecast (bot: ForecastService, proces per instrument)
- **Artefakt:** XAUUSD: data/forecast/runs/<run>/forecast_model.json; BTC: data/instruments/BTC/forecast/runs/…; rejestr registry.json per instrument
- **Instrumenty:** XAUUSD, BTC
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: BASE_FORECAST | opis: ZAIMPLEMENTOWANE_I_ZINTEGROWANE (XAUUSD: grid 5.0; BTC: grid 500 – hipoteza badawcza); parity loadera; brak testu na realnym MT5 w tym środowisku

## ml:legacy_s01_s12 – Legacy ML – Decision Tree / Legacy ML – XGBoost (CPU)

- **Aliasy:** legacy_ml, LEGACY_ML_DT, LEGACY_ML_XGB
- **Kategoria:** MODEL_TRAINED (rejestr: sh.models.REGISTRY)
- **Implementacja:** masterquo/ml/{features,labels,models,trainer,registry,service,router,offline}.py
- **Zadanie:** P(setup S01–S12 osiąga cel netto przed SL) dla potwierdzonej wersji setupu
- **Źródło danych:** setupy silnika na żywo (HIGH) + backfill z eksportu (APPROX, tylko gdy zadanie o to prosi)
- **TF:** TF setupu
- **Horyzont:** do wyjścia setupu
- **Strona:** oba (cecha kierunku)
- **Cechy:** MQ-FEAT-1.3.0 (ml/features.py; 1.0.0 + cechy stref PMW-ZONE-FEAT-1, semantyka stref SEM-2; modele <= 1.2.0 dostają blok SEM-1)
- **Etykieta:** MQ-LABEL-1.1.0 (koszty: spread+poślizg+prowizja)
- **Trainer:** ml/trainer.py (bloki fit/tune/calibrate/test, embargo 120 min); offline: training ml-offline
- **Loader:** ml/registry.py Bundle → MLService.predict (bot, baza aktywnego instrumentu)
- **Artefakt:** XAUUSD: data/ml/models + masterquo.sqlite; BTC: data/instruments/BTC/ml/{models,ml.sqlite}
- **Instrumenty:** XAUUSD, BTC
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: SETUP_EVENT | opis: ZINTEGROWANE per instrument; model z próbek APPROX = RESEARCH_APPROX (nigdy champion automatycznie)

## extind:indicator_context – Kontekst wskaźników SAR + IQ (reakcja)

- **Aliasy:** indicator_context
- **Kategoria:** MODEL_TRAINED (rejestr: sh.models.REGISTRY)
- **Implementacja:** backend/masterquo/extind/
- **Zadanie:** SCORE / probability
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** indicator_context
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: SETUP_EVENT (score polityki scalp (TP1 przed SL innego planu) – liczony per plan w scalp.indicator_context)

## ml_scalp:xgb_net_r – Scalp ML – XGBoost P(net_R > 0) + E[net_R] cyklu scalp (SCALP_NET_PROFIT_MARKET_V1, rodzina SCALP_MARKET)

- **Aliasy:** ml_scalp, ML_SCALP_NET_R
- **Kategoria:** MODEL_TRAINED (rejestr: sh.models.REGISTRY)
- **Implementacja:** masterquo/ml/scalp_task.py (zbiór, trening, selekcja, paczka), ml/service.py on_scalp_candidate (inferencja), scalp/service.py (wywołanie per kandydat)
- **Zadanie:** klasyfikator P(net_R pełnego cyklu > 0) + regresor E[net_R], osobno per (instrument, profile_hash, strona)
- **Źródło danych:** kandydaci ScalpMachine z replayu eksportu (profil instrumentu, wejście MARKET z wykonalnym fill)
- **TF:** M1 (wyzwalacz scalp; kontekst profilu)
- **Horyzont:** pełny cykl scalp (TP1/TP2, BE, wyjście czasowe – scalp/replay.py)
- **Strona:** BUY i SELL – osobne modele
- **Cechy:** SCALP-NET-FEAT-1.0.0 (scalp/strategy.py NET_FEATURES; brak = NaN, bez 0.0 za brak)
- **Etykieta:** y = 1 gdy net_R > 0 po kosztach (Bid/Ask, prowizja, poślizg); net_R – regresja
- **Trainer:** ml/scalp_task.py (XGBoost CPU hist, 4 foldy walk-forward FIT/TUNE/CALIBRATION/POLICY, Platt, polityka p_min × ev_min, holdout 20% raz)
- **Loader:** ml/scalp_task.selected_bundle → MLService.on_scalp_candidate (predykcja zapisana przed publikacją)
- **Artefakt:** data/ml_scalp/<INST>/runs/<run> (fixture_runs dla danych syntetycznych) + registry.json; role OBSERVE / SHADOW_GATE
- **Instrumenty:** XAUUSD, BTC
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: SETUP_EVENT (P(net R>0) innego cyklu scalp – liczony per plan w scalp.ml_scalp) | opis: ZAIMPLEMENTOWANE_I_ZINTEGROWANE (OBSERVE / SHADOW_GATE – polityka hipotetyczna wyświetlana w panelu, nie wysyła zleceń)

## nss:tcn – Neural Scalp System (TCN)

- **Aliasy:** nss
- **Kategoria:** MODEL_TRAINED (rejestr: sh.models.REGISTRY)
- **Implementacja:** backend/masterquo/lab/nss_service.py
- **Zadanie:** CLASS_PROBABILITIES / probability
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** neural_scalp
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: SETUP_EVENT (P(TP1_FIRST/SL_FIRST/TIMEOUT) innego setupu – liczony per plan w scalp.neural)

## flow:reaction_m1 – Flow context – model reakcji M1 (FLOW_CONTEXT_MOVE_M1_V1)

- **Aliasy:** flow_reaction
- **Kategoria:** MODEL_TRAINED (rejestr: sh.models.REGISTRY)
- **Implementacja:** backend/masterquo/lab/flow_context/
- **Zadanie:** CLASS_PROBABILITIES / probability
- **Źródło danych:** —
- **TF:** M1
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** flow_context
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: BASE_FORECAST (NOT_CONNECTED: model reakcji FLOW_CONTEXT_MOVE_M1_V1 trenowany (LOGREG / XGB), bez ścieżki inferencji na żywo – FlowSections liczy tylko Heikin / S-R / StopDistance i Markov3 (flow:markov3); replay tylko z CLI (F-17))

## context_ind:context_move_m5 – Context indicators – CONTEXT_MOVE_M5_V1

- **Aliasy:** CONTEXT_MOVE_M5_V1, context_move
- **Kategoria:** MODEL_TRAINED (rejestr: sh.models.REGISTRY)
- **Implementacja:** backend/masterquo/lab/context_ind/
- **Zadanie:** CLASS_PROBABILITIES / probability
- **Źródło danych:** —
- **TF:** M5
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** context_indicators
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: BASE_FORECAST (NOT_CONNECTED: model badawczy bez ścieżki inferencji na żywo (F-17))

## mm:align_mean – Align Mean (wspólna średnia, odległość w ATR)

- **Aliasy:** align_mean, mm_align_mean
- **Kategoria:** RULE_OR_MEASUREMENT (rejestr: mm.inventory.MODULES, sh.models.REGISTRY)
- **Implementacja:** backend/masterquo/mm/align_mean.py, mql5/MasterModels/Include/PMW/PMW_AlignMeanCore.mqh, mql5/MasterModels/Indicators/PMW_AlignMean.mq5
- **Zadanie:** STATE / mixed
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** NOT_APPLICABLE
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: CONTEXT_STATE (odległości od średniej per TF (<TF>_dist_points / _dist_pct / _dist_atr: punkty, %, ATR) – rekord STATE bez cech MetaModelu)

## mm:kalman_cross – Kalman crossover fast/slow (zamknięte świece)

- **Aliasy:** kalman, mm_kalman
- **Kategoria:** RULE_OR_MEASUREMENT (rejestr: mm.inventory.MODULES, sh.models.REGISTRY)
- **Implementacja:** backend/masterquo/mm/kalman.py, mql5/MasterModels/Experts/PMW_KalmanShadowEA.mq5, mql5/MasterModels/Include/PMW/PMW_Kalman.mqh, mql5/MasterModels/Indicators/PMW_KalmanCross.mq5
- **Zadanie:** FILTER_STATE / state
- **Źródło danych:** —
- **TF:** M5
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** NOT_APPLICABLE (state estimation; Q/R calibration = separate BUZOA job)
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: CONTEXT_FEATURE

## mm:breakout_zones – Breakout zones + robust volatility

- **Aliasy:** breakout_zones, mm_breakout
- **Kategoria:** RULE_OR_MEASUREMENT (rejestr: mm.inventory.MODULES, sh.models.REGISTRY)
- **Implementacja:** backend/masterquo/mm/breakout_zones.py, backend/masterquo/mm/robust_vol.py, mql5/MasterModels/Include/PMW/PMW_BreakoutCore.mqh, mql5/MasterModels/Indicators/PMW_BreakoutZones.mq5
- **Zadanie:** FILTER_STATE / state
- **Źródło danych:** —
- **TF:** M5
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** NOT_APPLICABLE
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: CONTEXT_FEATURE

## mm:multi_indicator – Multi-Indicator Strategy (RSI/SAR/HA/Stoch/CCI/W%R/Power)

- **Aliasy:** mm_multi_indicator, multi_indicator
- **Kategoria:** RULE_OR_MEASUREMENT (rejestr: mm.inventory.MODULES, sh.models.REGISTRY)
- **Implementacja:** backend/masterquo/mm/multi_indicator.py
- **Zadanie:** STATE / state
- **Źródło danych:** —
- **TF:** M5
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** NOT_APPLICABLE
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: CONTEXT_STATE

## mm:smc_fvg – SMC BoS/IDM/FVG continuation (głębokość cofnięcia 73% – parametr, nie skuteczność)

- **Aliasy:** mm_smc_fvg, smc_fvg
- **Kategoria:** RULE_OR_MEASUREMENT (rejestr: mm.inventory.MODULES, sh.models.REGISTRY)
- **Implementacja:** backend/masterquo/lab/context_ind/smc.py (reused), backend/masterquo/mm/smc_fvg.py
- **Zadanie:** STATE / state
- **Źródło danych:** —
- **TF:** M5
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** NOT_APPLICABLE
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: CONTEXT_STATE

## mm:gpr_logret – GPR Matérn 3/2 – prognoza log-zwrotu z niepewnością

- **Aliasy:** gpr, gpr_logret, gpr_logret:LIVE, mm_gpr
- **Kategoria:** MODEL_TRAINED (rejestr: mm.inventory.MODULES, sh.models.REGISTRY)
- **Implementacja:** backend/masterquo/mm/gpr.py, mql5/MasterModels/Experts/PMW_GPR_ShadowEA.mq5, mql5/MasterModels/Include/PMW/PMW_GPR.mqh, mql5/MasterModels/Indicators/PMW_GPR_Forecast.mq5
- **Zadanie:** REGRESSION / LOG_RETURN_H3_M5 / log_return
- **Źródło danych:** —
- **TF:** M5
- **Horyzont:** 3 świece M5
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** master_models
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: BASE_FORECAST

## mm:hdc_dir3 – HDC – hiperwektory binarne (DOWN/FLAT/UP)

- **Aliasy:** hdc, hdc_dir3, mm_hdc
- **Kategoria:** MODEL_TRAINED (rejestr: mm.inventory.MODULES, sh.models.REGISTRY)
- **Implementacja:** backend/masterquo/mm/hdc.py, mql5/MasterModels/Include/PMW/PMW_HDC.mqh
- **Zadanie:** SCORE / ratio
- **Źródło danych:** —
- **TF:** M5
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** master_models
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: BASE_FORECAST (margines HDC (nie prawdopodobieństwo); brak ścieżki na żywo bez artefaktu VALIDATED_SHADOW)

## mm:event_engine_dir3 – Event engine GRU + state stack + korelacja (+STFS)

- **Aliasy:** SEQ_GRU_EVENT, event_engine, event_engine_dir3, family:SEQ_GRU_EVENT, mm_event_engine
- **Kategoria:** MODEL_TRAINED (rejestr: mm.inventory.MODULES, sh.models.REGISTRY)
- **Implementacja:** backend/masterquo/mm/event_engine.py, backend/masterquo/mm/events.py, backend/masterquo/mm/kernels/state_stack.cl, mql5/MasterModels/Include/PMW/PMW_StateStack.mqh
- **Zadanie:** CLASS_PROBABILITIES / EVENT_UNITS_DIR3 / probability
- **Źródło danych:** —
- **TF:** EVENT
- **Horyzont:** 2 jednostki zdarzeń (16 zdarzeń/jednostka)
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** master_models
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: BASE_FORECAST

## mm:ste_flownet_ret – STE-FlowNet (adaptacja finansowa) – log-zwrot h zdarzeń

- **Aliasy:** mm_ste_flownet, ste_flownet, ste_flownet_ret
- **Kategoria:** MODEL_TRAINED (rejestr: mm.inventory.MODULES, sh.models.REGISTRY)
- **Implementacja:** backend/masterquo/mm/ste_flownet.py
- **Zadanie:** REGRESSION / log_return
- **Źródło danych:** —
- **TF:** EVENT
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** master_models
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: BASE_FORECAST (brak ścieżki na żywo (tylko artefakt badawczy); log-zwrot h zdarzeń)

## kronos:Kronos-small – Kronos-small (NeoQuasar, przetrenowany, 24,7M) – prognoza świec OHLC

- **Aliasy:** KRONOS_SMALL, Kronos-small, kronos
- **Kategoria:** MODEL_PRETRAINED (rejestr: sh.models.REGISTRY)
- **Implementacja:** backend/masterquo/kronos/, backend/kronos_runtime/
- **Zadanie:** REGRESSION / KRONOS_CLOSE_PATH_H* / price
- **Źródło danych:** —
- **TF:** M1, M3, M5, M15, M30, H1
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** —
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: BASE_FORECAST (pojedyncza ścieżka nie jest prawdopodobieństwem; pretrained ≠ dostrojony do brokera; interwały = dozwolone w ustawieniach Kronos (domyślnie włączone M5, M15))

## agent:claude – Agent Claude (weto, opis)

- **Aliasy:** agent
- **Kategoria:** AGENT (rejestr: sh.models.REGISTRY)
- **Implementacja:** —
- **Zadanie:** STATE / state
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** —
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: NOT_A_VOTE (opis / weto tekstowe agenta – bez p(win); poza meta-modelem)

## tsfm:chronos2 – Chronos-2 (amazon/chronos-2, 120M, przetrenowany) – kwantyle close

- **Aliasy:** CHRONOS2, Chronos-2, chronos2
- **Kategoria:** MODEL_PRETRAINED (rejestr: sh.models.REGISTRY)
- **Implementacja:** backend/masterquo/tsfm/, backend/tsfm_runtime/
- **Zadanie:** REGRESSION / TSFM_CLOSE_H* / price
- **Źródło danych:** —
- **TF:** M1, M3, M5, M15, M30, H1
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** —
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: BASE_FORECAST (amazon/chronos-2 (120M); kwantyle modelu, punkt = mediana; nieskalibrowane na danych brokera; interwały = dozwolone w ustawieniach TSFM (domyślnie włączone M5, M15))

## tsfm:granite_ttm – Granite TTM (IBM granite-timeseries-ttm-r2, 0,8M, przetrenowany) – prognoza punktowa close

- **Aliasy:** GRANITE_TTM, Granite TTM, granite_ttm
- **Kategoria:** MODEL_PRETRAINED (rejestr: sh.models.REGISTRY)
- **Implementacja:** backend/masterquo/tsfm/, backend/tsfm_runtime/
- **Zadanie:** REGRESSION / TSFM_CLOSE_H* / price
- **Źródło danych:** —
- **TF:** M1, M3, M5, M15, M30, H1
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** tsfm.granite_train
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: BASE_FORECAST (ibm-granite/granite-timeseries-ttm-r2 (TTM R2 512-96, 0,8M); prognoza punktowa (bez kwantyli); nieskalibrowana; 1.40 zamiast FinCast (FinCast: RETIRED, historia zachowana); interwały = dozwolone w ustawieniach TSFM (domyślnie włączone M5, M15))

## tsfm:tirex2 – TiRex-2 (NX-AI, przetrenowany) – kwantyle close

- **Aliasy:** TIREX2, TiRex-2, tirex2
- **Kategoria:** MODEL_PRETRAINED (rejestr: sh.models.REGISTRY)
- **Implementacja:** backend/masterquo/tsfm/, backend/tsfm_runtime/
- **Zadanie:** REGRESSION / TSFM_CLOSE_H* / price
- **Źródło danych:** —
- **TF:** M5, M15
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** —
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: BASE_FORECAST (rekordy z model_id tsfm:tirex2 (TsfmService, jak Chronos-2 / Granite TTM); kwantyle; nieskalibrowane na danych brokera)

## trainhub:TH_BASELINE – Centrum treningu – Bazowy – częstości klas: kierunek ruchu po kosztach

- **Aliasy:** TH_BASELINE
- **Kategoria:** MODEL_TRAINED (rejestr: sh.models.REGISTRY (th_direction), trainhub.learn.MODELS)
- **Implementacja:** masterquo/trainhub/learn.py, features.py (wspólne cechy trening/inferencja), dataset.py, registry.py, inference.py
- **Zadanie:** klasa DOWN/FLAT/UP zmiany zamknięcia po H świecach względem progu max(k×ATR14, koszt świecy)
- **Źródło danych:** magazyn świec data/marketdata/<INST> (eksport MT5 przyrostowy/historyczny, Parquet + CSV + manifest z sumami)
- **TF:** M1, M5, M15, M30
- **Horyzont:** h świec (per paczka)
- **Strona:** oba (klasy)
- **Cechy:** PMW-TH-FEAT-1 (zwroty, ATR, świeca, zmienność, RSI, EMA, z-score, aktywność ticków, spread, czas, cechy wyższych TF)
- **Etykieta:** PMW-TH-LABEL-1 (koszty: spread ze świecy + prowizja z historii transakcji albo założenie + poślizg-założenie); okna przez lukę sesji odrzucone
- **Trainer:** Centrum treningu / `python -m masterquo trainhub train|full --instrument XAUUSD|BTC` (domyślny zestaw bez --models: TH_BASELINE, TH_LOGREG, TH_HGB) albo `--profile smoke|research|full` (purged walk-forward + embargo, nietknięty holdout 20%, kalibracja temperaturą na dev, proces osobny)
- **Loader:** TrainhubInference (tylko AKTYWNA paczka po teście zgodności i predykcji; inaczej stan INCOMPATIBLE/ERROR bez wartości)
- **Artefakt:** data/trainhub/models/<INST>/<MODEL>_<TF>_H<h>/<wersja>/ (model.joblib, cechy, config, metryki, manifest danych, zależności, REPRODUCE.md, sha256)
- **Instrumenty:** XAUUSD, BTC
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: TOOL (baseline częstości klas – punkt odniesienia) | opis: ZAIMPLEMENTOWANE_I_ZINTEGROWANE (OBSERVATION – nie głosuje w strategiach); trening sprawdzony tylko na symulatorze (SYNTHETIC_TEST) – brak oceny na danych rzeczywistych

## trainhub:TH_LOGREG – Centrum treningu – Regresja logistyczna (wieloklasowa): kierunek ruchu po kosztach

- **Aliasy:** TH_LOGREG
- **Kategoria:** MODEL_TRAINED (rejestr: sh.models.REGISTRY (th_direction), trainhub.learn.MODELS)
- **Implementacja:** masterquo/trainhub/learn.py, features.py (wspólne cechy trening/inferencja), dataset.py, registry.py, inference.py
- **Zadanie:** klasa DOWN/FLAT/UP zmiany zamknięcia po H świecach względem progu max(k×ATR14, koszt świecy)
- **Źródło danych:** magazyn świec data/marketdata/<INST> (eksport MT5 przyrostowy/historyczny, Parquet + CSV + manifest z sumami)
- **TF:** M1, M5, M15, M30
- **Horyzont:** h świec (per paczka)
- **Strona:** oba (klasy)
- **Cechy:** PMW-TH-FEAT-1 (zwroty, ATR, świeca, zmienność, RSI, EMA, z-score, aktywność ticków, spread, czas, cechy wyższych TF)
- **Etykieta:** PMW-TH-LABEL-1 (koszty: spread ze świecy + prowizja z historii transakcji albo założenie + poślizg-założenie); okna przez lukę sesji odrzucone
- **Trainer:** Centrum treningu / `python -m masterquo trainhub train|full --instrument XAUUSD|BTC` (domyślny zestaw bez --models: TH_BASELINE, TH_LOGREG, TH_HGB) albo `--profile smoke|research|full` (purged walk-forward + embargo, nietknięty holdout 20%, kalibracja temperaturą na dev, proces osobny)
- **Loader:** TrainhubInference (tylko AKTYWNA paczka po teście zgodności i predykcji; inaczej stan INCOMPATIBLE/ERROR bez wartości)
- **Artefakt:** data/trainhub/models/<INST>/<MODEL>_<TF>_H<h>/<wersja>/ (model.joblib, cechy, config, metryki, manifest danych, zależności, REPRODUCE.md, sha256)
- **Instrumenty:** XAUUSD, BTC
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: BASE_FORECAST | opis: ZAIMPLEMENTOWANE_I_ZINTEGROWANE (OBSERVATION – nie głosuje w strategiach); trening sprawdzony tylko na symulatorze (SYNTHETIC_TEST) – brak oceny na danych rzeczywistych

## trainhub:TH_HGB – Centrum treningu – Gradient boosting (histogramowy): kierunek ruchu po kosztach

- **Aliasy:** TH_HGB
- **Kategoria:** MODEL_TRAINED (rejestr: sh.models.REGISTRY (th_direction), trainhub.learn.MODELS)
- **Implementacja:** masterquo/trainhub/learn.py, features.py (wspólne cechy trening/inferencja), dataset.py, registry.py, inference.py
- **Zadanie:** klasa DOWN/FLAT/UP zmiany zamknięcia po H świecach względem progu max(k×ATR14, koszt świecy)
- **Źródło danych:** magazyn świec data/marketdata/<INST> (eksport MT5 przyrostowy/historyczny, Parquet + CSV + manifest z sumami)
- **TF:** M1, M5, M15, M30
- **Horyzont:** h świec (per paczka)
- **Strona:** oba (klasy)
- **Cechy:** PMW-TH-FEAT-1 (zwroty, ATR, świeca, zmienność, RSI, EMA, z-score, aktywność ticków, spread, czas, cechy wyższych TF)
- **Etykieta:** PMW-TH-LABEL-1 (koszty: spread ze świecy + prowizja z historii transakcji albo założenie + poślizg-założenie); okna przez lukę sesji odrzucone
- **Trainer:** Centrum treningu / `python -m masterquo trainhub train|full --instrument XAUUSD|BTC` (domyślny zestaw bez --models: TH_BASELINE, TH_LOGREG, TH_HGB) albo `--profile research|full` (purged walk-forward + embargo, nietknięty holdout 20%, kalibracja temperaturą na dev, proces osobny)
- **Loader:** TrainhubInference (tylko AKTYWNA paczka po teście zgodności i predykcji; inaczej stan INCOMPATIBLE/ERROR bez wartości)
- **Artefakt:** data/trainhub/models/<INST>/<MODEL>_<TF>_H<h>/<wersja>/ (model.joblib, cechy, config, metryki, manifest danych, zależności, REPRODUCE.md, sha256)
- **Instrumenty:** XAUUSD, BTC
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: BASE_FORECAST | opis: ZAIMPLEMENTOWANE_I_ZINTEGROWANE (OBSERVATION – nie głosuje w strategiach); trening sprawdzony tylko na symulatorze (SYNTHETIC_TEST) – brak oceny na danych rzeczywistych

## trainhub:TH_XGB – Centrum treningu – XGBoost (CPU): kierunek ruchu po kosztach (tylko gdy pakiet xgboost jest zainstalowany)

- **Aliasy:** TH_XGB, family:TH_XGB
- **Kategoria:** MODEL_TRAINED (rejestr: modelhub.families (alias), sh.models.REGISTRY (th_direction), trainhub.learn.MODELS)
- **Implementacja:** masterquo/trainhub/learn.py, features.py (wspólne cechy trening/inferencja), dataset.py, registry.py, inference.py
- **Zadanie:** klasa DOWN/FLAT/UP zmiany zamknięcia po H świecach względem progu max(k×ATR14, koszt świecy)
- **Źródło danych:** magazyn świec data/marketdata/<INST> (eksport MT5 przyrostowy/historyczny, Parquet + CSV + manifest z sumami)
- **TF:** M1, M5, M15, M30
- **Horyzont:** h świec (per paczka)
- **Strona:** oba (klasy)
- **Cechy:** PMW-TH-FEAT-1 (zwroty, ATR, świeca, zmienność, RSI, EMA, z-score, aktywność ticków, spread, czas, cechy wyższych TF)
- **Etykieta:** PMW-TH-LABEL-1 (koszty: spread ze świecy + prowizja z historii transakcji albo założenie + poślizg-założenie); okna przez lukę sesji odrzucone
- **Trainer:** Centrum treningu / `python -m masterquo trainhub train|full --instrument XAUUSD|BTC --models TH_XGB` albo `--profile research|full` – NIE w domyślnym zestawie bez --models (TH_BASELINE, TH_LOGREG, TH_HGB) (purged walk-forward + embargo, nietknięty holdout 20%, kalibracja temperaturą na dev, proces osobny)
- **Loader:** TrainhubInference (tylko AKTYWNA paczka po teście zgodności i predykcji; inaczej stan INCOMPATIBLE/ERROR bez wartości)
- **Artefakt:** data/trainhub/models/<INST>/<MODEL>_<TF>_H<h>/<wersja>/ (model.joblib, cechy, config, metryki, manifest danych, zależności, REPRODUCE.md, sha256)
- **Instrumenty:** XAUUSD, BTC
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: BASE_FORECAST (alias rodziny family:TH_XGB – jeden artefakt, jeden trening, jeden głos) | opis: ZAIMPLEMENTOWANE_I_ZINTEGROWANE (OBSERVATION – nie głosuje w strategiach); trening sprawdzony tylko na symulatorze (SYNTHETIC_TEST) – brak oceny na danych rzeczywistych

## trainhub:TH_RF – Centrum treningu – Random Forest: kierunek ruchu po kosztach (permutation importance liczone na HOLDOUT (raport), class_weight balanced_subsample)

- **Aliasy:** TH_RF, family:TH_RF
- **Kategoria:** MODEL_TRAINED (rejestr: modelhub.families (alias), sh.models.REGISTRY (th_direction), trainhub.learn.MODELS)
- **Implementacja:** masterquo/trainhub/learn.py, features.py (wspólne cechy trening/inferencja), dataset.py, registry.py, inference.py
- **Zadanie:** klasa DOWN/FLAT/UP zmiany zamknięcia po H świecach względem progu max(k×ATR14, koszt świecy)
- **Źródło danych:** magazyn świec data/marketdata/<INST> (eksport MT5 przyrostowy/historyczny, Parquet + CSV + manifest z sumami)
- **TF:** M1, M5, M15, M30
- **Horyzont:** h świec (per paczka)
- **Strona:** oba (klasy)
- **Cechy:** PMW-TH-FEAT-1 (zwroty, ATR, świeca, zmienność, RSI, EMA, z-score, aktywność ticków, spread, czas, cechy wyższych TF)
- **Etykieta:** PMW-TH-LABEL-1 (koszty: spread ze świecy + prowizja z historii transakcji albo założenie + poślizg-założenie); okna przez lukę sesji odrzucone
- **Trainer:** Centrum treningu / `python -m masterquo trainhub train|full --instrument XAUUSD|BTC --models TH_RF` albo `--profile smoke|research|full` – NIE w domyślnym zestawie bez --models (TH_BASELINE, TH_LOGREG, TH_HGB) (purged walk-forward + embargo, nietknięty holdout 20%, kalibracja temperaturą na dev, proces osobny)
- **Loader:** TrainhubInference (tylko AKTYWNA paczka po teście zgodności i predykcji; inaczej stan INCOMPATIBLE/ERROR bez wartości)
- **Artefakt:** data/trainhub/models/<INST>/<MODEL>_<TF>_H<h>/<wersja>/ (model.joblib, cechy, config, metryki, manifest danych, zależności, REPRODUCE.md, sha256)
- **Instrumenty:** XAUUSD, BTC
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: BASE_FORECAST (alias rodziny family:TH_RF – jeden artefakt, jeden trening, jeden głos) | opis: ZAIMPLEMENTOWANE_I_ZINTEGROWANE (OBSERVATION – nie głosuje w strategiach); trening sprawdzony tylko na symulatorze (SYNTHETIC_TEST) – brak oceny na danych rzeczywistych

## trainhub:TH_SVM – Centrum treningu – SVM (skalowanie + kalibracja chronologiczna): kierunek ruchu po kosztach (jądro RBF tylko do 6000 wierszy, powyżej liniowe)

- **Aliasy:** TH_SVM, family:TH_SVM
- **Kategoria:** MODEL_TRAINED (rejestr: modelhub.families (alias), sh.models.REGISTRY (th_direction), trainhub.learn.MODELS)
- **Implementacja:** masterquo/trainhub/learn.py, features.py (wspólne cechy trening/inferencja), dataset.py, registry.py, inference.py
- **Zadanie:** klasa DOWN/FLAT/UP zmiany zamknięcia po H świecach względem progu max(k×ATR14, koszt świecy)
- **Źródło danych:** magazyn świec data/marketdata/<INST> (eksport MT5 przyrostowy/historyczny, Parquet + CSV + manifest z sumami)
- **TF:** M1, M5, M15, M30
- **Horyzont:** h świec (per paczka)
- **Strona:** oba (klasy)
- **Cechy:** PMW-TH-FEAT-1 (zwroty, ATR, świeca, zmienność, RSI, EMA, z-score, aktywność ticków, spread, czas, cechy wyższych TF)
- **Etykieta:** PMW-TH-LABEL-1 (koszty: spread ze świecy + prowizja z historii transakcji albo założenie + poślizg-założenie); okna przez lukę sesji odrzucone
- **Trainer:** Centrum treningu / `python -m masterquo trainhub train|full --instrument XAUUSD|BTC --models TH_SVM` albo `--profile smoke|research|full` – NIE w domyślnym zestawie bez --models (TH_BASELINE, TH_LOGREG, TH_HGB) (purged walk-forward + embargo, nietknięty holdout 20%, kalibracja temperaturą na dev, proces osobny)
- **Loader:** TrainhubInference (tylko AKTYWNA paczka po teście zgodności i predykcji; inaczej stan INCOMPATIBLE/ERROR bez wartości)
- **Artefakt:** data/trainhub/models/<INST>/<MODEL>_<TF>_H<h>/<wersja>/ (model.joblib, cechy, config, metryki, manifest danych, zależności, REPRODUCE.md, sha256)
- **Instrumenty:** XAUUSD, BTC
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: BASE_FORECAST (alias rodziny family:TH_SVM – jeden artefakt, jeden trening, jeden głos) | opis: ZAIMPLEMENTOWANE_I_ZINTEGROWANE (OBSERVATION – nie głosuje w strategiach); trening sprawdzony tylko na symulatorze (SYNTHETIC_TEST) – brak oceny na danych rzeczywistych

## family:TS_ARIMA – ARIMA (statsmodels) – prognoza log-zwrotu

- **Aliasy:** TS_ARIMA
- **Kategoria:** MODEL_TRAINED (rejestr: modelhub.families.registry)
- **Implementacja:** backend/masterquo/modelhub/families/arima.py
- **Zadanie:** REGRESSION / LOG_RETURN_H / log_return
- **Źródło danych:** —
- **TF:** M5
- **Horyzont:** [1, 3, 5] świec M5
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** modelhub.families.service (proces obok)
- **Loader:** modelhub.families.service
- **Artefakt:** <data>/model_families/TS_ARIMA/<instrument>/<run_id>
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: BASE_FORECAST

## family:TS_SARIMAX – SARIMAX (statsmodels) – zwroty H1 z kalendarzem sesji jako exog

- **Aliasy:** TS_SARIMAX
- **Kategoria:** MODEL_TRAINED (rejestr: modelhub.families.registry)
- **Implementacja:** backend/masterquo/modelhub/families/arima.py
- **Zadanie:** REGRESSION / LOG_RETURN_H / log_return
- **Źródło danych:** —
- **TF:** H1
- **Horyzont:** [1, 3, 5] świec H1
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** modelhub.families.service (proces obok)
- **Loader:** modelhub.families.service
- **Artefakt:** <data>/model_families/TS_SARIMAX/<instrument>/<run_id>
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: BASE_FORECAST

## family:VOL_GARCH – GARCH(1,1) (arch) – zmienność warunkowa

- **Aliasy:** VOL_GARCH
- **Kategoria:** MODEL_TRAINED (rejestr: modelhub.families.registry)
- **Implementacja:** backend/masterquo/modelhub/families/garch.py
- **Zadanie:** VOLATILITY / SIGMA_LOG_RETURN_H / sigma_return
- **Źródło danych:** —
- **TF:** M5
- **Horyzont:** [1, 6, 12] świec M5
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** modelhub.families.service (proces obok)
- **Loader:** modelhub.families.service
- **Artefakt:** <data>/model_families/VOL_GARCH/<instrument>/<run_id>
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: BASE_FORECAST

## family:MICROSTRUCTURE – Mikrostruktura – arkusz brokera (imbalance, OFI, microprice) + klasyfikator reakcji

- **Aliasy:** MICROSTRUCTURE
- **Kategoria:** MEASUREMENT (rejestr: modelhub.families.registry)
- **Implementacja:** backend/masterquo/modelhub/families/micro.py
- **Zadanie:** MICROSTRUCTURE / BOOK_STATE_AND_REACTION_10S / mixed
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** brak (pomiar stanu)
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** modelhub.families.service (proces obok)
- **Loader:** modelhub.families.service
- **Artefakt:** <data>/model_families/MICROSTRUCTURE/<instrument>/<run_id>
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: CONTEXT_FEATURE

## family:PAIR_COINT – Kointegracja pary + z-score (Engle-Granger)

- **Aliasy:** PAIR_COINT
- **Kategoria:** MODEL_TRAINED (rejestr: modelhub.families.registry)
- **Implementacja:** backend/masterquo/modelhub/families/pairs.py
- **Zadanie:** PAIR_RELATION / PAIR_SPREAD_Z / z_score
- **Źródło danych:** —
- **TF:** H1
- **Horyzont:** [1] świec H1
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** modelhub.families.service (proces obok)
- **Loader:** modelhub.families.service
- **Artefakt:** <data>/model_families/PAIR_COINT/<instrument>/<run_id>
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: CONTEXT_FEATURE

## family:STATARB – Arbitraż statystyczny – koszyk PCA + reszty (s-score)

- **Aliasy:** STATARB
- **Kategoria:** MODEL_TRAINED (rejestr: modelhub.families.registry)
- **Implementacja:** backend/masterquo/modelhub/families/pairs.py
- **Zadanie:** PAIR_RELATION / BASKET_RESIDUAL_S / z_score
- **Źródło danych:** —
- **TF:** H1
- **Horyzont:** [1] świec H1
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** modelhub.families.service (proces obok)
- **Loader:** modelhub.families.service
- **Artefakt:** <data>/model_families/STATARB/<instrument>/<run_id>
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: CONTEXT_FEATURE

## family:KALMAN_LS – Filtr Kalmana poziom + nachylenie (rozbudowa mm_kalman)

- **Aliasy:** KALMAN_LS
- **Kategoria:** MODEL_ESTIMATED (rejestr: modelhub.families.registry)
- **Implementacja:** backend/masterquo/modelhub/families/kalman_ls.py
- **Zadanie:** FILTER_STATE / TREND_STATE / mixed
- **Źródło danych:** —
- **TF:** M5
- **Horyzont:** [1] świec M5
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** modelhub.families.service (proces obok)
- **Loader:** modelhub.families.service
- **Artefakt:** <data>/model_families/KALMAN_LS/<instrument>/<run_id>
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: CONTEXT_FEATURE

## family:BREAKOUT – Breakout – wspólny moduł logiki wybicia (kanał, kompresja, potwierdzenie, retest)

- **Aliasy:** BREAKOUT
- **Kategoria:** MODEL_ESTIMATED (rejestr: modelhub.families.registry)
- **Implementacja:** backend/masterquo/modelhub/families/breakout.py
- **Zadanie:** FILTER_STATE / BREAKOUT_STATE / mixed
- **Źródło danych:** —
- **TF:** M5
- **Horyzont:** [1] świec M5
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** modelhub.families.service (proces obok)
- **Loader:** modelhub.families.service
- **Artefakt:** <data>/model_families/BREAKOUT/<instrument>/<run_id>
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: CONTEXT_FEATURE

## family:SEQ_LSTM – LSTM (PyTorch, .venv_deep) – rozkład kierunku po kosztach

- **Aliasy:** SEQ_LSTM
- **Kategoria:** MODEL_TRAINED (rejestr: modelhub.families.registry)
- **Implementacja:** backend/masterquo/modelhub/families/seq.py
- **Zadanie:** CLASS_PROBABILITIES / DIRECTION_H6_AFTER_COST / probability
- **Źródło danych:** —
- **TF:** M5
- **Horyzont:** [6] świec M5
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** modelhub.families.service (proces obok)
- **Loader:** modelhub.families.service
- **Artefakt:** <data>/model_families/SEQ_LSTM/<instrument>/<run_id>
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: BASE_FORECAST

## family:SEQ_GRU – GRU świecowy (PyTorch, .venv_deep) – rozkład kierunku po kosztach

- **Aliasy:** SEQ_GRU
- **Kategoria:** MODEL_TRAINED (rejestr: modelhub.families.registry)
- **Implementacja:** backend/masterquo/modelhub/families/seq.py
- **Zadanie:** CLASS_PROBABILITIES / DIRECTION_H6_AFTER_COST / probability
- **Źródło danych:** —
- **TF:** M5
- **Horyzont:** [6] świec M5
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** modelhub.families.service (proces obok)
- **Loader:** modelhub.families.service
- **Artefakt:** <data>/model_families/SEQ_GRU/<instrument>/<run_id>
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: BASE_FORECAST

## family:RL_PPO – PPO (Stable-Baselines3, Gymnasium replay) – propozycja ekspozycji

- **Aliasy:** RL_PPO
- **Kategoria:** MODEL_TRAINED (rejestr: modelhub.families.registry)
- **Implementacja:** backend/masterquo/modelhub/families/rl.py
- **Zadanie:** RL_ACTION / TARGET_EXPOSURE / action
- **Źródło danych:** —
- **TF:** M5
- **Horyzont:** brak (pomiar stanu)
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** modelhub.families.service (proces obok)
- **Loader:** modelhub.families.service
- **Artefakt:** <data>/model_families/RL_PPO/<instrument>/<run_id>
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: NOT_A_VOTE (akcja RL ≠ p(win))

## family:NLP_SENTIMENT – Sentyment tekstu – TF-IDF + regresja logistyczna

- **Aliasy:** NLP_SENTIMENT
- **Kategoria:** MODEL_TRAINED (rejestr: modelhub.families.registry)
- **Implementacja:** backend/masterquo/modelhub/families/nlp.py
- **Zadanie:** NLP_SENTIMENT / TEXT_SENTIMENT_3 / sentiment
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** brak (pomiar stanu)
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** modelhub.families.service (proces obok)
- **Loader:** modelhub.families.service
- **Artefakt:** <data>/model_families/NLP_SENTIMENT/<instrument>/<run_id>
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: CONTEXT_FEATURE (sentyment ≠ kierunek XAUUSD bez wyuczonego związku)

## lab:DUMMY – Lab DUMMY – częstość bazowa

- **Aliasy:** LAB_DUMMY
- **Kategoria:** BASELINE (rejestr: lab.protocol.FAMILIES, sh.models.REGISTRY (lab))
- **Implementacja:** masterquo/lab/protocol.py fit_family('DUMMY'), lab/nets.py, lab/minirocket.py
- **Zadanie:** klasyfikacja binarna LONG
- **Źródło danych:** eksport treningowy M5 (data/training/datasets/<INST>/<run>) albo bufor bota
- **TF:** M5
- **Horyzont:** 12 świec (60 min)
- **Strona:** LONG (tylko długie – nie oznaczać jako oba kierunki)
- **Cechy:** FS-1.0.0 (lab/features.py: zwroty, ATR, EMA gap, kinematyka, sesja; sekwencje 32×kanały dla sieci)
- **Etykieta:** potrójna bariera: TP 1.5×ATR przed SL 1.0×ATR w 12 świecach M5 (LBL-TB-1.0.0); SL i TP w tej samej świecy → SL (konserwatywnie)
- **Trainer:** masterquo/lab/protocol.py LabTrainer + training lab-offline (walk-forward 4 foldy, purge/embargo 12, holdout 20% raz)
- **Loader:** lab/protocol.py load_artifact → LabService._infer (bot), kontrola parity przy zapisie
- **Artefakt:** data/lab/models/<INST>/<model_id>/model.pkl + manifest.json (+ ACTIVE.json: aktywny per rodzina, rollback)
- **Instrumenty:** XAUUSD, BTC
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: TOOL (score innego zdarzenia niż TP setupu – cecha pod własną nazwą) | opis: MODEL_KONTROLNY (nie zapisywany jako artefakt); zapisywany jest model oceniany (fit na danych rozwojowych), bez refitu na train+holdout

## lab:RULE – Lab RULE – reguła odniesienia

- **Aliasy:** LAB_RULE
- **Kategoria:** BASELINE (rejestr: lab.protocol.FAMILIES, sh.models.REGISTRY (lab))
- **Implementacja:** masterquo/lab/protocol.py fit_family('RULE'), lab/nets.py, lab/minirocket.py
- **Zadanie:** klasyfikacja binarna LONG
- **Źródło danych:** eksport treningowy M5 (data/training/datasets/<INST>/<run>) albo bufor bota
- **TF:** M5
- **Horyzont:** 12 świec (60 min)
- **Strona:** LONG (tylko długie – nie oznaczać jako oba kierunki)
- **Cechy:** FS-1.0.0 (lab/features.py: zwroty, ATR, EMA gap, kinematyka, sesja; sekwencje 32×kanały dla sieci)
- **Etykieta:** potrójna bariera: TP 1.5×ATR przed SL 1.0×ATR w 12 świecach M5 (LBL-TB-1.0.0); SL i TP w tej samej świecy → SL (konserwatywnie)
- **Trainer:** masterquo/lab/protocol.py LabTrainer + training lab-offline (walk-forward 4 foldy, purge/embargo 12, holdout 20% raz)
- **Loader:** lab/protocol.py load_artifact → LabService._infer (bot), kontrola parity przy zapisie
- **Artefakt:** data/lab/models/<INST>/<model_id>/model.pkl + manifest.json (+ ACTIVE.json: aktywny per rodzina, rollback)
- **Instrumenty:** XAUUSD, BTC
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: TOOL (score innego zdarzenia niż TP setupu – cecha pod własną nazwą) | opis: MODEL_KONTROLNY; zapisywany jest model oceniany (fit na danych rozwojowych), bez refitu na train+holdout

## lab:LOGREG – Lab regresja logistyczna

- **Aliasy:** LAB_LOGREG
- **Kategoria:** MODEL_TRAINED (rejestr: lab.protocol.FAMILIES, sh.models.REGISTRY (lab))
- **Implementacja:** masterquo/lab/protocol.py fit_family('LOGREG'), lab/nets.py, lab/minirocket.py
- **Zadanie:** klasyfikacja binarna LONG
- **Źródło danych:** eksport treningowy M5 (data/training/datasets/<INST>/<run>) albo bufor bota
- **TF:** M5
- **Horyzont:** 12 świec (60 min)
- **Strona:** LONG (tylko długie – nie oznaczać jako oba kierunki)
- **Cechy:** FS-1.0.0 (lab/features.py: zwroty, ATR, EMA gap, kinematyka, sesja; sekwencje 32×kanały dla sieci)
- **Etykieta:** potrójna bariera: TP 1.5×ATR przed SL 1.0×ATR w 12 świecach M5 (LBL-TB-1.0.0); SL i TP w tej samej świecy → SL (konserwatywnie)
- **Trainer:** masterquo/lab/protocol.py LabTrainer + training lab-offline (walk-forward 4 foldy, purge/embargo 12, holdout 20% raz)
- **Loader:** lab/protocol.py load_artifact → LabService._infer (bot), kontrola parity przy zapisie
- **Artefakt:** data/lab/models/<INST>/<model_id>/model.pkl + manifest.json (+ ACTIVE.json: aktywny per rodzina, rollback)
- **Instrumenty:** XAUUSD, BTC
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: BASE_FORECAST (score innego zdarzenia niż TP setupu – cecha pod własną nazwą) | opis: ZAIMPLEMENTOWANE_I_ZINTEGROWANE; zapisywany jest model oceniany (fit na danych rozwojowych), bez refitu na train+holdout

## lab:TREE – Lab drzewo decyzyjne (≠ legacy Decision Tree: inne pytanie – bariera LONG M5, nie setup S01–S12)

- **Aliasy:** LAB_TREE
- **Kategoria:** MODEL_TRAINED (rejestr: lab.protocol.FAMILIES, sh.models.REGISTRY (lab))
- **Implementacja:** masterquo/lab/protocol.py fit_family('TREE'), lab/nets.py, lab/minirocket.py
- **Zadanie:** klasyfikacja binarna LONG
- **Źródło danych:** eksport treningowy M5 (data/training/datasets/<INST>/<run>) albo bufor bota
- **TF:** M5
- **Horyzont:** 12 świec (60 min)
- **Strona:** LONG (tylko długie – nie oznaczać jako oba kierunki)
- **Cechy:** FS-1.0.0 (lab/features.py: zwroty, ATR, EMA gap, kinematyka, sesja; sekwencje 32×kanały dla sieci)
- **Etykieta:** potrójna bariera: TP 1.5×ATR przed SL 1.0×ATR w 12 świecach M5 (LBL-TB-1.0.0); SL i TP w tej samej świecy → SL (konserwatywnie)
- **Trainer:** masterquo/lab/protocol.py LabTrainer + training lab-offline (walk-forward 4 foldy, purge/embargo 12, holdout 20% raz)
- **Loader:** lab/protocol.py load_artifact → LabService._infer (bot), kontrola parity przy zapisie
- **Artefakt:** data/lab/models/<INST>/<model_id>/model.pkl + manifest.json (+ ACTIVE.json: aktywny per rodzina, rollback)
- **Instrumenty:** XAUUSD, BTC
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: BASE_FORECAST (score innego zdarzenia niż TP setupu – cecha pod własną nazwą) | opis: ZAIMPLEMENTOWANE_I_ZINTEGROWANE; zapisywany jest model oceniany (fit na danych rozwojowych), bez refitu na train+holdout

## lab:MINIROCKET – Lab MiniRocket (numpy) + klasyfikator liniowy

- **Aliasy:** LAB_MINIROCKET
- **Kategoria:** MODEL_TRAINED (rejestr: lab.protocol.FAMILIES, sh.models.REGISTRY (lab))
- **Implementacja:** masterquo/lab/protocol.py fit_family('MINIROCKET'), lab/nets.py, lab/minirocket.py
- **Zadanie:** klasyfikacja binarna LONG
- **Źródło danych:** eksport treningowy M5 (data/training/datasets/<INST>/<run>) albo bufor bota
- **TF:** M5
- **Horyzont:** 12 świec (60 min)
- **Strona:** LONG (tylko długie – nie oznaczać jako oba kierunki)
- **Cechy:** FS-1.0.0 (lab/features.py: zwroty, ATR, EMA gap, kinematyka, sesja; sekwencje 32×kanały dla sieci)
- **Etykieta:** potrójna bariera: TP 1.5×ATR przed SL 1.0×ATR w 12 świecach M5 (LBL-TB-1.0.0); SL i TP w tej samej świecy → SL (konserwatywnie)
- **Trainer:** masterquo/lab/protocol.py LabTrainer + training lab-offline (walk-forward 4 foldy, purge/embargo 12, holdout 20% raz)
- **Loader:** lab/protocol.py load_artifact → LabService._infer (bot), kontrola parity przy zapisie
- **Artefakt:** data/lab/models/<INST>/<model_id>/model.pkl + manifest.json (+ ACTIVE.json: aktywny per rodzina, rollback)
- **Instrumenty:** XAUUSD, BTC
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: BASE_FORECAST (score innego zdarzenia niż TP setupu – cecha pod własną nazwą) | opis: ZAIMPLEMENTOWANE_I_ZINTEGROWANE; zapisywany jest model oceniany (fit na danych rozwojowych), bez refitu na train+holdout

## lab:XGB – Lab XGBoost (CPU)

- **Aliasy:** LAB_XGB
- **Kategoria:** MODEL_TRAINED (rejestr: lab.protocol.FAMILIES, sh.models.REGISTRY (lab))
- **Implementacja:** masterquo/lab/protocol.py fit_family('XGB'), lab/nets.py, lab/minirocket.py
- **Zadanie:** klasyfikacja binarna LONG
- **Źródło danych:** eksport treningowy M5 (data/training/datasets/<INST>/<run>) albo bufor bota
- **TF:** M5
- **Horyzont:** 12 świec (60 min)
- **Strona:** LONG (tylko długie – nie oznaczać jako oba kierunki)
- **Cechy:** FS-1.0.0 (lab/features.py: zwroty, ATR, EMA gap, kinematyka, sesja; sekwencje 32×kanały dla sieci)
- **Etykieta:** potrójna bariera: TP 1.5×ATR przed SL 1.0×ATR w 12 świecach M5 (LBL-TB-1.0.0); SL i TP w tej samej świecy → SL (konserwatywnie)
- **Trainer:** masterquo/lab/protocol.py LabTrainer + training lab-offline (walk-forward 4 foldy, purge/embargo 12, holdout 20% raz)
- **Loader:** lab/protocol.py load_artifact → LabService._infer (bot), kontrola parity przy zapisie
- **Artefakt:** data/lab/models/<INST>/<model_id>/model.pkl + manifest.json (+ ACTIVE.json: aktywny per rodzina, rollback)
- **Instrumenty:** XAUUSD, BTC
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: BASE_FORECAST (score innego zdarzenia niż TP setupu – cecha pod własną nazwą) | opis: ZAIMPLEMENTOWANE_I_ZINTEGROWANE; zapisywany jest model oceniany (fit na danych rozwojowych), bez refitu na train+holdout

## lab:RESNET1D – Lab ResNet1D (numpy)

- **Aliasy:** LAB_RESNET1D
- **Kategoria:** MODEL_TRAINED (rejestr: lab.protocol.FAMILIES, sh.models.REGISTRY (lab))
- **Implementacja:** masterquo/lab/protocol.py fit_family('RESNET1D'), lab/nets.py, lab/minirocket.py
- **Zadanie:** klasyfikacja binarna LONG
- **Źródło danych:** eksport treningowy M5 (data/training/datasets/<INST>/<run>) albo bufor bota
- **TF:** M5
- **Horyzont:** 12 świec (60 min)
- **Strona:** LONG (tylko długie – nie oznaczać jako oba kierunki)
- **Cechy:** FS-1.0.0 (lab/features.py: zwroty, ATR, EMA gap, kinematyka, sesja; sekwencje 32×kanały dla sieci)
- **Etykieta:** potrójna bariera: TP 1.5×ATR przed SL 1.0×ATR w 12 świecach M5 (LBL-TB-1.0.0); SL i TP w tej samej świecy → SL (konserwatywnie)
- **Trainer:** masterquo/lab/protocol.py LabTrainer + training lab-offline (walk-forward 4 foldy, purge/embargo 12, holdout 20% raz)
- **Loader:** lab/protocol.py load_artifact → LabService._infer (bot), kontrola parity przy zapisie
- **Artefakt:** data/lab/models/<INST>/<model_id>/model.pkl + manifest.json (+ ACTIVE.json: aktywny per rodzina, rollback)
- **Instrumenty:** XAUUSD, BTC
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: BASE_FORECAST (score innego zdarzenia niż TP setupu – cecha pod własną nazwą) | opis: ZAIMPLEMENTOWANE_I_ZINTEGROWANE; zapisywany jest model oceniany (fit na danych rozwojowych), bez refitu na train+holdout

## lab:SEW_SNN – Lab SEW-SNN (sieć impulsowa, numpy)

- **Aliasy:** LAB_SEW_SNN
- **Kategoria:** MODEL_TRAINED (rejestr: lab.protocol.FAMILIES, sh.models.REGISTRY (lab))
- **Implementacja:** masterquo/lab/protocol.py fit_family('SEW_SNN'), lab/nets.py, lab/minirocket.py
- **Zadanie:** klasyfikacja binarna LONG
- **Źródło danych:** eksport treningowy M5 (data/training/datasets/<INST>/<run>) albo bufor bota
- **TF:** M5
- **Horyzont:** 12 świec (60 min)
- **Strona:** LONG (tylko długie – nie oznaczać jako oba kierunki)
- **Cechy:** FS-1.0.0 (lab/features.py: zwroty, ATR, EMA gap, kinematyka, sesja; sekwencje 32×kanały dla sieci)
- **Etykieta:** potrójna bariera: TP 1.5×ATR przed SL 1.0×ATR w 12 świecach M5 (LBL-TB-1.0.0); SL i TP w tej samej świecy → SL (konserwatywnie)
- **Trainer:** masterquo/lab/protocol.py LabTrainer + training lab-offline (walk-forward 4 foldy, purge/embargo 12, holdout 20% raz)
- **Loader:** lab/protocol.py load_artifact → LabService._infer (bot), kontrola parity przy zapisie
- **Artefakt:** data/lab/models/<INST>/<model_id>/model.pkl + manifest.json (+ ACTIVE.json: aktywny per rodzina, rollback)
- **Instrumenty:** XAUUSD, BTC
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: BASE_FORECAST (score innego zdarzenia niż TP setupu – cecha pod własną nazwą) | opis: ZAIMPLEMENTOWANE_I_ZINTEGROWANE; zapisywany jest model oceniany (fit na danych rozwojowych), bez refitu na train+holdout

## lab:LOGREG_PCA – Eksperyment: LOGREG na PCA

- **Aliasy:** LAB_LOGREG_PCA
- **Kategoria:** RESEARCH (rejestr: lab.protocol.EXPERIMENTS, sh.models.REGISTRY (lab))
- **Implementacja:** masterquo/lab/protocol.py fit_family('LOGREG_PCA'), lab/nets.py, lab/minirocket.py
- **Zadanie:** klasyfikacja binarna LONG
- **Źródło danych:** eksport treningowy M5 (data/training/datasets/<INST>/<run>) albo bufor bota
- **TF:** M5
- **Horyzont:** 12 świec (60 min)
- **Strona:** LONG (tylko długie – nie oznaczać jako oba kierunki)
- **Cechy:** FS-1.0.0 (lab/features.py: zwroty, ATR, EMA gap, kinematyka, sesja; sekwencje 32×kanały dla sieci)
- **Etykieta:** potrójna bariera: TP 1.5×ATR przed SL 1.0×ATR w 12 świecach M5 (LBL-TB-1.0.0); SL i TP w tej samej świecy → SL (konserwatywnie)
- **Trainer:** masterquo/lab/protocol.py LabTrainer + training lab-offline (walk-forward 4 foldy, purge/embargo 12, holdout 20% raz)
- **Loader:** lab/protocol.py load_artifact → LabService._infer (bot), kontrola parity przy zapisie
- **Artefakt:** data/lab/models/<INST>/<model_id>/model.pkl + manifest.json (+ ACTIVE.json: aktywny per rodzina, rollback)
- **Instrumenty:** XAUUSD, BTC
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: BASE_FORECAST (eksperyment badawczy (PCA / GMM / neutralizacja) – wariant LOGREG, score innego zdarzenia niż TP setupu; artefakt w trybie ALL (training lab-offline, profil PEŁNY TRENING) albo gdy wygra selekcję; t_activate przypina rolę research -> rekord lab:<X> w Quant) | opis: EKSPERYMENT; zapisywany jest model oceniany (fit na danych rozwojowych), bez refitu na train+holdout

## lab:LOGREG_GMM_AUG – Eksperyment: LOGREG z cechami reżimu GMM

- **Aliasy:** LAB_LOGREG_GMM_AUG
- **Kategoria:** RESEARCH (rejestr: lab.protocol.EXPERIMENTS, sh.models.REGISTRY (lab))
- **Implementacja:** masterquo/lab/protocol.py fit_family('LOGREG_GMM_AUG'), lab/nets.py, lab/minirocket.py
- **Zadanie:** klasyfikacja binarna LONG
- **Źródło danych:** eksport treningowy M5 (data/training/datasets/<INST>/<run>) albo bufor bota
- **TF:** M5
- **Horyzont:** 12 świec (60 min)
- **Strona:** LONG (tylko długie – nie oznaczać jako oba kierunki)
- **Cechy:** FS-1.0.0 (lab/features.py: zwroty, ATR, EMA gap, kinematyka, sesja; sekwencje 32×kanały dla sieci)
- **Etykieta:** potrójna bariera: TP 1.5×ATR przed SL 1.0×ATR w 12 świecach M5 (LBL-TB-1.0.0); SL i TP w tej samej świecy → SL (konserwatywnie)
- **Trainer:** masterquo/lab/protocol.py LabTrainer + training lab-offline (walk-forward 4 foldy, purge/embargo 12, holdout 20% raz)
- **Loader:** lab/protocol.py load_artifact → LabService._infer (bot), kontrola parity przy zapisie
- **Artefakt:** data/lab/models/<INST>/<model_id>/model.pkl + manifest.json (+ ACTIVE.json: aktywny per rodzina, rollback)
- **Instrumenty:** XAUUSD, BTC
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: BASE_FORECAST (eksperyment badawczy (PCA / GMM / neutralizacja) – wariant LOGREG, score innego zdarzenia niż TP setupu; artefakt w trybie ALL (training lab-offline, profil PEŁNY TRENING) albo gdy wygra selekcję; t_activate przypina rolę research -> rekord lab:<X> w Quant) | opis: EKSPERYMENT; zapisywany jest model oceniany (fit na danych rozwojowych), bez refitu na train+holdout

## lab:LOGREG_NEUTRALIZED – Eksperyment: LOGREG z neutralizacją czynników

- **Aliasy:** LAB_LOGREG_NEUTRALIZED
- **Kategoria:** RESEARCH (rejestr: lab.protocol.EXPERIMENTS, sh.models.REGISTRY (lab))
- **Implementacja:** masterquo/lab/protocol.py fit_family('LOGREG_NEUTRALIZED'), lab/nets.py, lab/minirocket.py
- **Zadanie:** klasyfikacja binarna LONG
- **Źródło danych:** eksport treningowy M5 (data/training/datasets/<INST>/<run>) albo bufor bota
- **TF:** M5
- **Horyzont:** 12 świec (60 min)
- **Strona:** LONG (tylko długie – nie oznaczać jako oba kierunki)
- **Cechy:** FS-1.0.0 (lab/features.py: zwroty, ATR, EMA gap, kinematyka, sesja; sekwencje 32×kanały dla sieci)
- **Etykieta:** potrójna bariera: TP 1.5×ATR przed SL 1.0×ATR w 12 świecach M5 (LBL-TB-1.0.0); SL i TP w tej samej świecy → SL (konserwatywnie)
- **Trainer:** masterquo/lab/protocol.py LabTrainer + training lab-offline (walk-forward 4 foldy, purge/embargo 12, holdout 20% raz)
- **Loader:** lab/protocol.py load_artifact → LabService._infer (bot), kontrola parity przy zapisie
- **Artefakt:** data/lab/models/<INST>/<model_id>/model.pkl + manifest.json (+ ACTIVE.json: aktywny per rodzina, rollback)
- **Instrumenty:** XAUUSD, BTC
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: BASE_FORECAST (eksperyment badawczy (PCA / GMM / neutralizacja) – wariant LOGREG, score innego zdarzenia niż TP setupu; artefakt w trybie ALL (training lab-offline, profil PEŁNY TRENING) albo gdy wygra selekcję; t_activate przypina rolę research -> rekord lab:<X> w Quant) | opis: EKSPERYMENT; zapisywany jest model oceniany (fit na danych rozwojowych), bez refitu na train+holdout

## si:MQ_RESNEXT1D_V2 – Structure Intelligence MQ_RESNEXT1D_V2

- **Kategoria:** MODEL_TRAINED (rejestr: lab.structure_nets.FAMILIES, sh.models.REGISTRY (si_move))
- **Implementacja:** backend/masterquo/lab/structure_nets.py, backend/masterquo/lab/si_service.py
- **Zadanie:** CLASS_PROBABILITIES / M1_MOVE_H3/5/15 (DOWN/FLAT/UP + kwantyle r_h/ATR) / probability
- **Źródło danych:** —
- **TF:** M1
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** training (structure_intelligence)
- **Loader:** lab.si_service
- **Artefakt:** <data>/structure_intelligence/<instrument>/
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: BASE_FORECAST (prognoza SHADOW STRUCTURE_MOVE_M1_V1 liczona na żywo przy każdej zamkniętej M1 (scalp.service -> scalp.dashboard (MTF) -> lab.si_service.forecast) tylko dla rodziny wskazanej w rejestrze SI shadow[STRUCTURE_MOVE_M1_V1]; archiwum si_forecasts / si_outcomes, migawka MTF i agent (get_structure_intelligence); bez adaptera Quant (PMW-PRED-2))

## si:MQ_SEW_RESNET1D_V2 – Structure Intelligence MQ_SEW_RESNET1D_V2

- **Kategoria:** MODEL_TRAINED (rejestr: lab.structure_nets.FAMILIES, sh.models.REGISTRY (si_move))
- **Implementacja:** backend/masterquo/lab/structure_nets.py, backend/masterquo/lab/si_service.py
- **Zadanie:** CLASS_PROBABILITIES / M1_MOVE_H3/5/15 (DOWN/FLAT/UP + kwantyle r_h/ATR) / probability
- **Źródło danych:** —
- **TF:** M1
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** training (structure_intelligence)
- **Loader:** lab.si_service
- **Artefakt:** <data>/structure_intelligence/<instrument>/
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: BASE_FORECAST (prognoza SHADOW STRUCTURE_MOVE_M1_V1 liczona na żywo przy każdej zamkniętej M1 (scalp.service -> scalp.dashboard (MTF) -> lab.si_service.forecast) tylko dla rodziny wskazanej w rejestrze SI shadow[STRUCTURE_MOVE_M1_V1]; archiwum si_forecasts / si_outcomes, migawka MTF i agent (get_structure_intelligence); bez adaptera Quant (PMW-PRED-2))

## si:MQ_SEW_RESNEXT_EB_V1 – Structure Intelligence MQ_SEW_RESNEXT_EB_V1

- **Kategoria:** MODEL_TRAINED (rejestr: lab.structure_nets.FAMILIES, sh.models.REGISTRY (si_move))
- **Implementacja:** backend/masterquo/lab/structure_nets.py, backend/masterquo/lab/si_service.py
- **Zadanie:** CLASS_PROBABILITIES / M1_MOVE_H3/5/15 (DOWN/FLAT/UP + kwantyle r_h/ATR) / probability
- **Źródło danych:** —
- **TF:** M1
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** training (structure_intelligence)
- **Loader:** lab.si_service
- **Artefakt:** <data>/structure_intelligence/<instrument>/
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: BASE_FORECAST (prognoza SHADOW STRUCTURE_MOVE_M1_V1 liczona na żywo przy każdej zamkniętej M1 (scalp.service -> scalp.dashboard (MTF) -> lab.si_service.forecast) tylko dla rodziny wskazanej w rejestrze SI shadow[STRUCTURE_MOVE_M1_V1]; archiwum si_forecasts / si_outcomes, migawka MTF i agent (get_structure_intelligence); bez adaptera Quant (PMW-PRED-2))

## si:MQ_MINIROCKET_RIDGE_V2 – Structure Intelligence MQ_MINIROCKET_RIDGE_V2

- **Kategoria:** MODEL_TRAINED (rejestr: lab.si_families.FAMILIES, sh.models.REGISTRY (si_move))
- **Implementacja:** backend/masterquo/lab/si_families.py, backend/masterquo/lab/si_service.py
- **Zadanie:** CLASS_PROBABILITIES / M1_MOVE_H3/5/15 (DOWN/FLAT/UP + kwantyle r_h/ATR) / probability
- **Źródło danych:** —
- **TF:** M1
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** training (structure_intelligence)
- **Loader:** lab.si_service
- **Artefakt:** <data>/structure_intelligence/<instrument>/
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: BASE_FORECAST (prognoza SHADOW STRUCTURE_MOVE_M1_V1 liczona na żywo przy każdej zamkniętej M1 (scalp.service -> scalp.dashboard (MTF) -> lab.si_service.forecast) tylko dla rodziny wskazanej w rejestrze SI shadow[STRUCTURE_MOVE_M1_V1]; archiwum si_forecasts / si_outcomes, migawka MTF i agent (get_structure_intelligence); bez adaptera Quant (PMW-PRED-2))

## si:MQ_SPIKE_BRAIN_FINANCE_V1 – Structure Intelligence MQ_SPIKE_BRAIN_FINANCE_V1

- **Kategoria:** MODEL_TRAINED (rejestr: lab.si_families.FAMILIES, sh.models.REGISTRY (si_move))
- **Implementacja:** backend/masterquo/lab/si_families.py, backend/masterquo/lab/si_service.py
- **Zadanie:** CLASS_PROBABILITIES / M1_MOVE_H3/5/15 (DOWN/FLAT/UP + kwantyle r_h/ATR) / probability
- **Źródło danych:** —
- **TF:** M1
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** training (structure_intelligence)
- **Loader:** lab.si_service
- **Artefakt:** <data>/structure_intelligence/<instrument>/
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: BASE_FORECAST (prognoza SHADOW STRUCTURE_MOVE_M1_V1 liczona na żywo przy każdej zamkniętej M1 (scalp.service -> scalp.dashboard (MTF) -> lab.si_service.forecast) tylko dla rodziny wskazanej w rejestrze SI shadow[STRUCTURE_MOVE_M1_V1]; archiwum si_forecasts / si_outcomes, migawka MTF i agent (get_structure_intelligence); bez adaptera Quant (PMW-PRED-2))

## mm:buzoa – BUZOA Optimization Engine

- **Kategoria:** OPTIMIZER (rejestr: mm.inventory.MODULES)
- **Implementacja:** backend/masterquo/mm/buzoa.py
- **Zadanie:** —
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** NOT_APPLICABLE (optimiser)
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: TOOL (narzędzie / infrastruktura / proces uczenia – nie osobny głos modelu)

## mm:sdom – SDOm Optimization Engine

- **Kategoria:** NO_SPEC (rejestr: mm.inventory.MODULES)
- **Implementacja:** —
- **Zadanie:** —
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** NOT_APPLICABLE
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: NO_SPEC; walidacja: NOT_APPLICABLE; rola w Quant Core: TOOL (brak specyfikacji w paczce – algorytm nie jest odtwarzany z nazwy)

## mm:stfs – S3CE-Net / STFS (training-time sampling)

- **Kategoria:** TRAINABLE (rejestr: mm.inventory.MODULES)
- **Implementacja:** backend/masterquo/mm/stfs.py
- **Zadanie:** —
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** APPLICABLE (as a training strategy)
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: TOOL (narzędzie / infrastruktura / proces uczenia – nie osobny głos modelu)

## mm:quant_momentum – Quant Ultimate Momentum Pro / Quant 2nd Model / Momentum AI Fusion

- **Kategoria:** NO_SPEC (rejestr: mm.inventory.MODULES)
- **Implementacja:** —
- **Zadanie:** —
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** UNKNOWN
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: NO_SPEC; walidacja: NOT_APPLICABLE; rola w Quant Core: NONE (brak specyfikacji w paczce – algorytm nie jest odtwarzany z nazwy)

## mm:renko – Renko Regression Forecasting

- **Kategoria:** NO_SPEC (rejestr: mm.inventory.MODULES)
- **Implementacja:** —
- **Zadanie:** —
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** UNKNOWN
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: NO_SPEC; walidacja: NOT_APPLICABLE; rola w Quant Core: NONE (brak specyfikacji w paczce – algorytm nie jest odtwarzany z nazwy)

## mm:head_shoulders – Head & Shoulders Structure Detector

- **Kategoria:** NO_SPEC (rejestr: mm.inventory.MODULES)
- **Implementacja:** backend/masterquo/analysis/chart_patterns.py (istniejący detektor formacji, w tym H&S)
- **Zadanie:** —
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** NOT_APPLICABLE
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: NO_SPEC; walidacja: NOT_APPLICABLE; rola w Quant Core: NONE (brak specyfikacji w paczce – algorytm nie jest odtwarzany z nazwy)

## mm:data_grabber – Multi-TF Data Grabber Lite

- **Kategoria:** NO_SPEC (rejestr: mm.inventory.MODULES)
- **Implementacja:** backend/masterquo/forecast/export.py (istniejący eksport historii zamkniętych świec + metadane + sha256)
- **Zadanie:** —
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** NOT_APPLICABLE
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: NO_SPEC; walidacja: NOT_APPLICABLE; rola w Quant Core: TOOL (brak specyfikacji w paczce – algorytm nie jest odtwarzany z nazwy)

## mm:tsvp – Tick Session Volume Profile

- **Kategoria:** VISUALIZATION (rejestr: mm.inventory.MODULES)
- **Implementacja:** backend/masterquo/mm/tsvp.py, mql5/MasterModels/Include/PMW/PMW_TSVPCore.mqh, mql5/MasterModels/Indicators/PMW_TickSessionVP.mq5
- **Zadanie:** —
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** NOT_APPLICABLE
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: TOOL (narzędzie / infrastruktura / proces uczenia – nie osobny głos modelu)

## mm:mathbench – Math Engine Fidelity Benchmark

- **Kategoria:** BENCHMARK (rejestr: mm.inventory.MODULES)
- **Implementacja:** backend/masterquo/mm/mathbench.py, mql5/MathFidelity/train_export_model.py, mql5/MathFidelity/Experts/MathFidelityBenchmark_EA.mq5, mql5/MathFidelity/Indicators/FidelityMonitor.mq5, mql5/MathFidelity/Scripts/MathFidelity_SelfTest.mq5
- **Zadanie:** —
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** NOT_APPLICABLE
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: TOOL (narzędzie / infrastruktura / proces uczenia – nie osobny głos modelu)

## mm:chart_sync – MT5 Multi-Timeframe Chart Synchronization

- **Kategoria:** NO_SPEC (rejestr: mm.inventory.MODULES)
- **Implementacja:** frontend (istniejąca opcjonalna synchronizacja wykresów w panelu, J1)
- **Zadanie:** —
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** NOT_APPLICABLE
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: NO_SPEC; walidacja: NOT_APPLICABLE; rola w Quant Core: TOOL (brak specyfikacji w paczce – algorytm nie jest odtwarzany z nazwy)

## mm:fusion_board – Evidence board (cross-model integration layer, discovered need)

- **Kategoria:** DATA_INFRA (rejestr: mm.inventory.MODULES)
- **Implementacja:** backend/masterquo/mm/fusion.py
- **Zadanie:** —
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** NOT_APPLICABLE
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: TOOL (narzędzie / infrastruktura / proces uczenia – nie osobny głos modelu)

## analysis:montecarlo – Monte Carlo ścieżek cen (PMW-MC-1) – P(TP przed SL w horyzoncie)

- **Aliasy:** MONTE_CARLO_PATHS
- **Kategoria:** SIMULATION (rejestr: runtime.py)
- **Implementacja:** masterquo/montecarlo/engine.py, validate.py, service.py
- **Zadanie:** prawdopodobieństwo, że cena dojdzie do TP przed SL w H świecach M1 (każdy poziom osobno) + zasięg ruchu ±X; świeca z TP i SL = przedział ostrożny–optymistyczny
- **Źródło danych:** zamknięte świece M1 bota (na żywo) / eksport MT5 M1 (+ opcjonalne ticki Bid/Ask rozstrzygające kolejność w świecy) – walidacja
- **TF:** M1
- **Horyzont:** H świec M1 (domyślnie 60; scenariusz SCALPING 30)
- **Strona:** BUY i SELL – strona Bid/Ask, spread ze świecy
- **Cechy:** brak cech uczonych: losowanie całych świec (OHLC względem otwarcia) – IID / blokowe / warunkowane reżimem ATR i godziną sesji, skalowane do bieżącego ATR
- **Etykieta:** rzeczywiste TP przed SL w H świecach (walidacja; ticki, gdy są) – dane wyłącznie sprzed chwili oceny
- **Trainer:** `python -m masterquo montecarlo validate` / 31_MONTE_CARLO_WALIDACJA.bat / zadanie runnera monte_carlo: walk-forward CAL/TEST z embargo H, model bazowy = klimatologia, Brier / log loss / kalibracja, CI bootstrap, kalibrator izotoniczny
- **Loader:** MonteCarloService (własny wątek; bufor zamkniętych świec bota) → /api/v1/montecarlo/*, /api/v1/sh/scenario
- **Artefakt:** data/montecarlo/<INST>/registry.json + runs/<run>/report.json (aktywny kalibrator tylko z REAL_USER_DATA z przewagą; rollback: montecarlo rollback)
- **Instrumenty:** XAUUSD, BTC
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: SIMULATION (MODEL_SIMULATED – wynik symulacji, nie prawdopodobieństwo skalibrowane na zdarzeniach) | opis: ZAIMPLEMENTOWANE_I_ZINTEGROWANE; bez kalibracji = prawdopodobieństwo w modelu (tak opisane w panelu); walidacja tylko na danych syntetycznych w tym środowisku (werdykt TEST_TECHNICZNY)

## analysis:zones – Mapa stref (PMW-ZONES)

- **Kategoria:** ANALYSIS (rejestr: runtime.py)
- **Implementacja:** backend/masterquo/zones/
- **Zadanie:** —
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** —
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: CONTEXT_STATE (rekord STATE (ZONE_MAP_SUMMARY) w migawce Quant bez cech MetaModelu – quant/features.py nie mapuje stref; cechy zone_* trafiają do kandydata i ledgera oceny (evaluation.zone_context))

## analysis:market_zones – Strefy rynkowe M1/M5/M15/M30 (PMW-MZ-1) – S/R, popyt/podaż, FVG, order blocks, EQH/EQL, konfluencja

- **Aliasy:** MARKET_ZONES_MZ1
- **Kategoria:** ANALYSIS (rejestr: runtime.py)
- **Implementacja:** masterquo/zones/market.py, zones/market_service.py (panel Wykresy → Strefy rynkowe)
- **Zadanie:** detekcja stref z jawnymi regułami potwierdzenia, testów i unieważnienia – nie jest modelem do trenowania
- **Źródło danych:** zamknięte świece M1/M5/M15/M30 dokładnego symbolu przez bridge (XAUUSD-, BTCUSDT-)
- **TF:** M1, M5, M15, M30
- **Horyzont:** —
- **Strona:** kierunek strefy (wzrostowa / spadkowa / neutralna)
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** brak (reguły; parametry skalowane ATR i profilem instrumentu)
- **Loader:** MarketZonesService (zadania na przycisk / aktualizacja po zamknięciu świecy)
- **Artefakt:** data/zones/market_zones.sqlite (historia stref i zdarzeń)
- **Instrumenty:** XAUUSD, BTC
- **Status:** kod: IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: NOT_A_VOTE (wizualizacja panelu Strefy rynkowe – liczone na żądanie (job) / w panelu, brak cyklu niezależnego od panelu; bez adaptera Quant i konsumenta cech) | opis: REGUŁY – zaimplementowane i zintegrowane; jakość 0–100 nie jest prawdopodobieństwem; EQH/EQL = płynność wnioskowana z OHLC

## analysis:indicators – Wskaźniki PMW-IND-1 (AVWAP sesja/zdarzenie/manualny, semiwariancja, percentyl spreadu, cechy profilu sesji, mikrostruktura arkusza/OFI, relacja DXY)

- **Kategoria:** ANALYSIS (rejestr: runtime.py)
- **Implementacja:** backend/masterquo/indicators/
- **Zadanie:** —
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** —
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: CONTEXT_STATE

## analysis:svp – Session Volume Profile (PMW-SVP-1)

- **Kategoria:** ANALYSIS (rejestr: runtime.py)
- **Implementacja:** backend/masterquo/svp/, backend/masterquo/sh/pack/features.py
- **Zadanie:** —
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** —
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: GATE_EXISTING (profil poprzedniej sesji (svp.engine.compute na zamkniętych M5, tick volume = aktywność feedu, nie wolumen obrotu) jest warunkiem wejścia wariantów pakietu SH PMW_HG08 / PMW_SC10 (value_area_rejection: brak profilu = NO_DATA, bez setupu); profile użytkownika – panel; Quant nie dubluje bramki)

## analysis:dxy_correlation – Korelacja XAUUSD–DXY (PMW-IND-1 dxy)

- **Kategoria:** ANALYSIS (rejestr: runtime.py)
- **Implementacja:** backend/masterquo/indicators/
- **Zadanie:** —
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** —
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: CONTEXT_FEATURE

## analysis:walls – Walls D1 (σ: import IV → IV ręczna → HV_PROXY domyślnie)

- **Kategoria:** ANALYSIS (rejestr: runtime.py)
- **Implementacja:** backend/masterquo/analysis/walls.py, backend/masterquo/analysis/iv_import.py
- **Zadanie:** —
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** —
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: GATE_EXISTING (bez importu IV źródłem σ jest zmienność historyczna D1 (HV_PROXY, close-to-close), nie rynek opcji; IV_SOURCED niezaimplementowane (NOT_CONFIGURED); brak źródła = UNAVAILABLE, nie zero; poziomy ścian są wejściem strategii S12 (ścieżka A) – Quant ich nie dubluje)

## analysis:evaluation – AI Setup Probability Engine (PMW-EVAL)

- **Kategoria:** ANALYSIS (rejestr: runtime.py)
- **Implementacja:** backend/masterquo/evaluation/
- **Zadanie:** —
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** —
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: SETUP_EVENT

## quant:metamodel – PMW Quant MetaModel (logistyczny + net R ridge, OOF, kalibracja)

- **Kategoria:** META_MODEL (rejestr: runtime.py)
- **Implementacja:** backend/masterquo/quant/metamodel.py
- **Zadanie:** —
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** —
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: META_MODEL

## ext:catboost – CatBoost

- **Kategoria:** NOT_IMPLEMENTED (rejestr: lab/traceability.py (wzmianka))
- **Implementacja:** —
- **Zadanie:** —
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** —
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: NOT_IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: NONE (nie istnieje w kodzie – nie dodano fikcyjnego adaptera)

## quant:tabicl_v2 – TabICLv2 (estymator confidence kandydata, in-context)

- **Kategoria:** MODEL_PRETRAINED (rejestr: quant.ids.EXTRA_PRODUCERS (1.46))
- **Implementacja:** backend/masterquo/quant/tabicl.py, backend/tabicl_runtime/
- **Zadanie:** —
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** —
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: SETUP_EVENT (wynik per kandydat w pamięci QuantService (nieutrwalany) – brak samodzielnej predykcji)

## flow:markov3 – Markov3 / Markov-diff flow (MQ_MARKOV3_FLOW_V1)

- **Kategoria:** MODEL_TRAINED (rejestr: quant.ids.EXTRA_PRODUCERS (1.46))
- **Implementacja:** backend/masterquo/lab/flow_context/markov.py
- **Zadanie:** —
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** —
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: CONTEXT_FEATURE (liczony w komórkach Structure Intelligence (panel) – bez adaptera Quant)

## si:LOGREG – Structure Intelligence LOGREG (FAMILIES_ALL)

- **Kategoria:** MODEL_TRAINED (rejestr: quant.ids.EXTRA_PRODUCERS (1.46))
- **Implementacja:** backend/masterquo/lab/structure_task.py
- **Zadanie:** —
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** —
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: BASE_FORECAST (rodzina bazowa SI – prognoza SHADOW STRUCTURE_MOVE_M1_V1 liczona na żywo przy każdej zamkniętej M1 (scalp.service -> scalp.dashboard (MTF) -> lab.si_service.forecast) tylko dla rodziny wskazanej w rejestrze SI shadow[STRUCTURE_MOVE_M1_V1]; archiwum si_forecasts / si_outcomes, migawka MTF i agent (get_structure_intelligence); bez adaptera Quant (PMW-PRED-2))

## si:XGB – Structure Intelligence XGB (FAMILIES_ALL)

- **Kategoria:** MODEL_TRAINED (rejestr: quant.ids.EXTRA_PRODUCERS (1.46))
- **Implementacja:** backend/masterquo/lab/structure_task.py
- **Zadanie:** —
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** —
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: BASE_FORECAST (rodzina bazowa SI – prognoza SHADOW STRUCTURE_MOVE_M1_V1 liczona na żywo przy każdej zamkniętej M1 (scalp.service -> scalp.dashboard (MTF) -> lab.si_service.forecast) tylko dla rodziny wskazanej w rejestrze SI shadow[STRUCTURE_MOVE_M1_V1]; archiwum si_forecasts / si_outcomes, migawka MTF i agent (get_structure_intelligence); bez adaptera Quant (PMW-PRED-2))

## quotes:MQ_NEWTONIAN_QUOTES_V2 – QuoteEngine (kinematyka notowań)

- **Kategoria:** RULE_OR_MEASUREMENT (rejestr: quant.ids.EXTRA_PRODUCERS (1.46))
- **Implementacja:** backend/masterquo/lab/quotes.py
- **Zadanie:** —
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** —
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: CONTEXT_FEATURE (wątek si-quotes – stan panelu SI, bez adaptera Quant)

## lab:M29_fourier – Lab M29 Fourier (prognoza archiwizowana)

- **Kategoria:** RULE_OR_MEASUREMENT (rejestr: quant.ids.EXTRA_PRODUCERS (1.46))
- **Implementacja:** backend/masterquo/lab/service.py
- **Zadanie:** —
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** —
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: TOOL (archiwum lab_forecasts i ocena – obserwacja, nie głos)

## lab:M31_tick_kinematics – Lab M31 kinematyka ticków (legacy obok QuoteEngine)

- **Kategoria:** RULE_OR_MEASUREMENT (rejestr: quant.ids.EXTRA_PRODUCERS (1.46))
- **Implementacja:** backend/masterquo/lab/service.py
- **Zadanie:** —
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** —
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: TOOL (stan panelu lab – obserwacja)

## lab:M42_trade_pad – Lab M42 trade pad (kalkulator)

- **Kategoria:** TOOL (rejestr: quant.ids.EXTRA_PRODUCERS (1.46))
- **Implementacja:** backend/masterquo/api/app.py
- **Zadanie:** —
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** —
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: TOOL (kalkulator API na żądanie – nie model)

## lab:M39_M41_edge – Lab M39–M41 RepaintInspector / edge drift / bootstrap

- **Kategoria:** TOOL (rejestr: quant.ids.EXTRA_PRODUCERS (1.46))
- **Implementacja:** backend/masterquo/lab/service.py
- **Zadanie:** —
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** —
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: TOOL (narzędzia diagnostyczne – nie głos)

## research:graph50 – Research Graph50 (SCORE per cel)

- **Kategoria:** RESEARCH (rejestr: quant.ids.EXTRA_PRODUCERS (1.46))
- **Implementacja:** backend/masterquo/research/
- **Zadanie:** —
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** —
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: BASE_FORECAST (rekordy z jawnym canonical_id research:graph50:<cel>)

## research:g7_smc_radar – Research G7 SMC radar

- **Kategoria:** RESEARCH (rejestr: quant.ids.EXTRA_PRODUCERS (1.46))
- **Implementacja:** backend/masterquo/research/
- **Zadanie:** —
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** —
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: CONTEXT_FEATURE

## research:sdformerflow – Research SDformerFlow (TH_SDFORMERFLOW)

- **Kategoria:** RESEARCH (rejestr: quant.ids.EXTRA_PRODUCERS (1.46))
- **Implementacja:** backend/masterquo/research/
- **Zadanie:** —
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** —
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: BASE_FORECAST (wymaga środowiska z torch 2.14.1)

## mm:kalman_params – Parametry Kalmana (kalibracja BUZOA)

- **Kategoria:** TRAINABLE (rejestr: quant.ids.EXTRA_PRODUCERS (1.46))
- **Implementacja:** backend/masterquo/mm/orchestrator.py
- **Zadanie:** —
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** —
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: TOOL (kandydat parametrów – serwis używa domyślnej konfiguracji (brak ścieżki na żywo))

## mm:robust_vol – Robust volatility (część breakout_zones)

- **Kategoria:** RULE_OR_MEASUREMENT (rejestr: quant.ids.EXTRA_PRODUCERS (1.46))
- **Implementacja:** backend/masterquo/mm/
- **Zadanie:** —
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** —
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: CONTEXT_FEATURE (pole rekordu MM live – cechą Quant nie jest)

## mm:drift – Drift (PMW-MM)

- **Kategoria:** RULE_OR_MEASUREMENT (rejestr: quant.ids.EXTRA_PRODUCERS (1.46))
- **Implementacja:** backend/masterquo/mm/drift.py
- **Zadanie:** —
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** —
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: TOOL (pole rekordu MM live)

## mm:bat_encoder – BAT encoder (losowe wagi, SHADOW_UNTRAINED)

- **Kategoria:** RESEARCH (rejestr: quant.ids.EXTRA_PRODUCERS (1.46))
- **Implementacja:** backend/masterquo/mm/, backend/masterquo/api/wf32_routes.py
- **Zadanie:** —
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** —
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: NOT_A_VOTE (tylko API /api/v1/models/bat/shadow; wagi niewytrenowane)

## extind:sar_context – Kontekst SAR (kalibracja siatki)

- **Kategoria:** RULE_OR_MEASUREMENT (rejestr: quant.ids.EXTRA_PRODUCERS (1.46))
- **Implementacja:** backend/masterquo/extind/
- **Zadanie:** —
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** —
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: CONTEXT_FEATURE (kontekst snapshotu ACTIVE / agenta – bez adaptera Quant)

## extind:knowledge – Reguły wiedzy IND-K01..K12

- **Kategoria:** RULE_OR_MEASUREMENT (rejestr: quant.ids.EXTRA_PRODUCERS (1.46))
- **Implementacja:** backend/masterquo/extind/knowledge.py
- **Zadanie:** —
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** —
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: NOT_A_VOTE (opis dla agenta – nie głos)

## extind:IQ_GOLD_GANN – IQ Gold Gann (wskaźnik MT5, eksport kopert)

- **Kategoria:** NATIVE_MQL5 (rejestr: quant.ids.EXTRA_PRODUCERS (1.46))
- **Implementacja:** mql5/PMW_ExtIndicatorExporter.mq5
- **Zadanie:** —
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** —
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: CONTEXT_FEATURE (natywny wskaźnik licencjonowany – działa tylko w terminalu MT5)

## extind:IQ_STAR_LINES – IQ Star Lines (wskaźnik MT5, eksport kopert)

- **Kategoria:** NATIVE_MQL5 (rejestr: quant.ids.EXTRA_PRODUCERS (1.46))
- **Implementacja:** mql5/PMW_ExtIndicatorExporter.mq5
- **Zadanie:** —
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** —
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: CONTEXT_FEATURE (natywny wskaźnik licencjonowany – działa tylko w terminalu MT5)

## extind:PAL02M – PAL02M (tożsamość nieustalona)

- **Kategoria:** NO_SPEC (rejestr: quant.ids.EXTRA_PRODUCERS (1.46))
- **Implementacja:** config/extind_manifests_v1.json
- **Zadanie:** —
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** —
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: NO_SPEC; walidacja: NOT_APPLICABLE; rola w Quant Core: NONE (NO_SPEC: tożsamość narzędzia niepotwierdzona – algorytm nie jest odtwarzany z nazwy)

## strategies:regime – MarketRegimeEngine MQ-REGIME-1.0.0 (wybór strategii ACTIVE)

- **Kategoria:** RULE_OR_MEASUREMENT (rejestr: quant.ids.EXTRA_PRODUCERS (1.46))
- **Implementacja:** backend/masterquo/strategies/regime.py
- **Zadanie:** —
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** —
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: GATE_EXISTING (bramka ścieżki A – Quant jej nie dubluje)

## analysis:signals – Poziomy / range M5 / MITP / neutralizacja

- **Kategoria:** RULE_OR_MEASUREMENT (rejestr: quant.ids.EXTRA_PRODUCERS (1.46))
- **Implementacja:** backend/masterquo/analysis/
- **Zadanie:** —
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** —
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: GATE_EXISTING (warunki setupów ścieżki A (S12) – Quant ich nie dubluje)

## analytics:session_engine – Silnik sesji (boxy sesyjne)

- **Kategoria:** RULE_OR_MEASUREMENT (rejestr: quant.ids.EXTRA_PRODUCERS (1.46))
- **Implementacja:** backend/masterquo/analytics/
- **Zadanie:** —
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** —
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: CONTEXT_FEATURE (wejście rule:liquidity (OBSERVE))

## engine:volzones – Strefy zmienności (panel)

- **Kategoria:** RULE_OR_MEASUREMENT (rejestr: quant.ids.EXTRA_PRODUCERS (1.46))
- **Implementacja:** backend/masterquo/engine/service.py
- **Zadanie:** —
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** —
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: NOT_A_VOTE (tylko API / kontekst agenta)

## apollo:market_trap – Market trap (SHADOW, ostrzeżenia)

- **Kategoria:** RULE_OR_MEASUREMENT (rejestr: quant.ids.EXTRA_PRODUCERS (1.46))
- **Implementacja:** backend/masterquo/apollo/
- **Zadanie:** —
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** —
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: NOT_A_VOTE (tylko GET /api/v1/market-trap)

## baskets:sfb – Strategy Filter Bucket koszyków FX

- **Kategoria:** RULE_OR_MEASUREMENT (rejestr: quant.ids.EXTRA_PRODUCERS (1.46))
- **Implementacja:** backend/masterquo/baskets/sfb.py
- **Zadanie:** —
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** —
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: GATE_EXISTING (filtr koszyków (domyślnie OFF) – Quant go nie dubluje)

## ml:decision_tree_ranker – Decision tree ranker (WF3.2)

- **Kategoria:** MODEL_TRAINED (rejestr: quant.ids.EXTRA_PRODUCERS (1.46))
- **Implementacja:** backend/masterquo/api/wf32_routes.py
- **Zadanie:** —
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** —
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_VALIDATED; rola w Quant Core: TOOL (nigdy nie trenowany w aplikacji – API zwraca FALLBACK_BASELINE)

## ml:association_rules – Reguły asocjacyjne (WF3.2)

- **Kategoria:** RULE_OR_MEASUREMENT (rejestr: quant.ids.EXTRA_PRODUCERS (1.46))
- **Implementacja:** backend/masterquo/api/wf32_routes.py
- **Zadanie:** —
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** —
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: NOT_A_VOTE (tylko API (OBSERVE))

## ml:pt_directional_skill – Test Pesarana–Timmermanna (WF3.2)

- **Kategoria:** TOOL (rejestr: quant.ids.EXTRA_PRODUCERS (1.46))
- **Implementacja:** backend/masterquo/api/wf32_routes.py
- **Zadanie:** —
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** —
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: TOOL (miara trafności na danych wywołującego – nie model)

## ml:change_point_engine – Change points PELT (WF3.2)

- **Kategoria:** RULE_OR_MEASUREMENT (rejestr: quant.ids.EXTRA_PRODUCERS (1.46))
- **Implementacja:** backend/masterquo/api/wf32_routes.py
- **Zadanie:** —
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** —
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: NOT_A_VOTE (tylko API)

## forecast:long_horizon – Rozkład 24–72 h (WF3.2)

- **Kategoria:** RULE_OR_MEASUREMENT (rejestr: quant.ids.EXTRA_PRODUCERS (1.46))
- **Implementacja:** backend/masterquo/api/wf32_routes.py
- **Zadanie:** —
- **Źródło danych:** —
- **TF:** —
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** —
- **Loader:** —
- **Artefakt:** —
- **Instrumenty:** —
- **Status:** kod: IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: NOT_A_VOTE (tylko API i eksport)

## forecast:double_retest_v2 – Maszyna stanów Double Retest v2

- **Aliasy:** DOUBLE_RETEST_V2
- **Kategoria:** RULE_OR_MEASUREMENT (rejestr: quant.ids.EXTRA_PRODUCERS (1.46))
- **Implementacja:** masterquo/forecast/double_retest.py
- **Zadanie:** reguła setupu (bez trenowania)
- **Źródło danych:** bary bota
- **TF:** M5/M30
- **Horyzont:** —
- **Strona:** oba
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** brak (reguła)
- **Loader:** ForecastService
- **Artefakt:** —
- **Instrumenty:** XAUUSD, BTC
- **Status:** kod: IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: CONTEXT_FEATURE (flagi w rekordzie prognozy – bez adaptera Quant) | opis: REGUŁA – nie jest modelem do trenowania

## scalp:C_policy – Scalp C – ocena polityki HEDGE_PARTIAL vs REDUCE

- **Aliasy:** SCALP_C
- **Kategoria:** TOOL (rejestr: quant.ids.EXTRA_PRODUCERS (1.46))
- **Implementacja:** masterquo/scalp/replay.py, report.hedge_summary
- **Zadanie:** porównanie polityk w replayu OHLC (bez ticków) – NIE jest siecią ani klasyfikatorem
- **Źródło danych:** replay eksportu M1
- **TF:** M1
- **Horyzont:** cykl
- **Strona:** oba
- **Cechy:** —
- **Etykieta:** wynik R polityk
- **Trainer:** brak (ewaluacja polityki)
- **Loader:** —
- **Artefakt:** raport runu scalp
- **Instrumenty:** XAUUSD, BTC
- **Status:** kod: IMPLEMENTED; walidacja: NOT_APPLICABLE; rola w Quant Core: TOOL (wynik replayu w rejestrze scalp – nie predykcja) | opis: EWALUACJA_POLITYKI – hedge pozostaje SHADOW/REDUCE

# Poza rejestrem kanonicznym

Opisy, których identyfikator nie odpowiada żadnej pozycji `quant/inventory` – zachowane jako opis, nie są pozycją rejestru.

## SCALP_PROFILE – Profil scalp Range→Sweep→Retest (automat stanów)

- **Uwaga:** brak w rejestrze kanonicznym (quant/ids, quant/inventory) – opis zachowany, nie jest pozycją rejestru
- **Implementacja:** masterquo/scalp/strategy.py + config/scalp_profile_v1.json / scalp_profile_BTC_v1.json
- **Zadanie:** reguła
- **Źródło danych:** bary bota
- **TF:** H1/M30/M15 kontekst, M5 zakres, M1 wyzwalacz
- **Horyzont:** —
- **Strona:** oba
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** brak
- **Loader:** ScalpService (profil per aktywne aktywo)
- **Artefakt:** —
- **Instrumenty:** XAUUSD, BTC
- **Status:** REGUŁA

## LAB_MARKOV – Macierz Markowa 3 stanów (moduł estymowany)

- **Uwaga:** brak w rejestrze kanonicznym (quant/ids, quant/inventory) – opis zachowany, nie jest pozycją rejestru
- **Implementacja:** masterquo/lab/market.py markov()
- **Zadanie:** rozkład stanu następnej świecy
- **Źródło danych:** bary bota
- **TF:** M5
- **Horyzont:** 1 świeca
- **Strona:** nie dotyczy
- **Cechy:** zwrot close-to-close
- **Etykieta:** stan DOWN/FLAT/UP
- **Trainer:** estymacja w oknie 500 świec kończącym się na ostatniej zamkniętej (wygładzanie Laplace'a) – bez osobnego treningu
- **Loader:** LabService (na żywo)
- **Artefakt:** —
- **Instrumenty:** XAUUSD, BTC
- **Status:** ESTYMOWANY_ONLINE; walidacja: archiwum prognoz punkt-w-czasie (Dane i diagnostyka)

## LAB_ACD – ACD(1,1) aktywności ticków (moduł estymowany)

- **Uwaga:** brak w rejestrze kanonicznym (quant/ids, quant/inventory) – opis zachowany, nie jest pozycją rejestru
- **Implementacja:** masterquo/lab/ticks.py fit_acd()
- **Zadanie:** oczekiwany czas do kolejnego ticka
- **Źródło danych:** ticki copy_ticks_from
- **TF:** tick
- **Horyzont:** następne zdarzenie
- **Strona:** nie dotyczy
- **Cechy:** czasy między tickami skorygowane dobowo
- **Etykieta:** —
- **Trainer:** QMLE wykładnicze, ograniczenia a+b<1 z konstrukcji – estymacja online
- **Loader:** LabService
- **Artefakt:** —
- **Instrumenty:** XAUUSD, BTC
- **Status:** ESTYMOWANY_ONLINE; minimum 300 zdarzeń, inaczej warming_up

## STRATEGIES_S01_S12 – Strategie S01–S12

- **Uwaga:** brak w rejestrze kanonicznym (quant/ids, quant/inventory) – opis zachowany, nie jest pozycją rejestru
- **Implementacja:** masterquo/strategies/*
- **Zadanie:** reguły setupów (strumień dla legacy ML)
- **Źródło danych:** bary bota / backfill z eksportu z symbolem instrumentu
- **TF:** M5–D1
- **Horyzont:** —
- **Strona:** oba
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** brak
- **Loader:** ActiveEngine
- **Artefakt:** —
- **Instrumenty:** XAUUSD, BTC
- **Status:** REGUŁY
