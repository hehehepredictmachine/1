# Inwentaryzacja komponentów obliczeniowych – Apollo23 Quant Core

Wygenerowano: 2026-11-28T11:22:04+00:00 · instrument: XAUUSD · tryb: OFFLINE (bez działającego bota – stany reguł i usług NOT_EVALUATED) · generator: `python -m masterquo quant inventory` (PMW-QUANT-INV-1)

Plik maszynowy: `docs/quant/INVENTORY.json`. Kanoniczne identyfikatory i aliasy: `backend/masterquo/quant/ids.py`.

## Pokrycie (cztery osobne miary)

* **Inwentaryzacja:** rozpoznano 126 komponentów, sklasyfikowano 126; rozwinięto 3 wierszy grupowych; złożono 87 aliasów.
* **Adaptery:** zaimplementowanych 118; z adapterem/odbiorcą 58; uzasadnione NOT_APPLICABLE 60; brakujące: brak.
* **Gotowość operacyjna:** ocenionych 0; z działającym wyjściem na żywo 0 (brak); sondy OK z adapterem: 0. liczone z opublikowanej generacji Quant Core (ważny, świeży wynik READY); offline – nieoceniane.
* **Gotowość analityczna:** wymagających walidacji 61; zwalidowanych dla roli 0. pełne pokrycie katalogu nie oznacza gotowości modeli.

Kategorie: AGENT=1, ANALYSIS=7, BASELINE=2, BENCHMARK=1, DATA_INFRA=1, MEASUREMENT=1, META_MODEL=1, MODEL_ESTIMATED=2, MODEL_PRETRAINED=5, MODEL_TRAINED=44, NATIVE_MQL5=2, NOT_IMPLEMENTED=1, NO_SPEC=7, OPTIMIZER=1, RESEARCH=7, RULE_OR_MEASUREMENT=35, SIMULATION=1, TOOL=4, TRAINABLE=2, VISUALIZATION=1

## Komponenty

| Kanoniczny id | Aliasy | Kategoria | Zadanie / jednostka | TF / horyzont | Stan kodu | Stan działania | Walidacja | Rola w Quant Core | Adapter / uzasadnienie |
|---|---|---|---|---|---|---|---|---|---|
| `rule:data_quality` | data_quality | RULE_OR_MEASUREMENT | STATE / state | – | IMPLEMENTED | NOT_EVALUATED (liczone z bieżących świec – stan tylko przy działającym bocie) | NOT_APPLICABLE | istniejąca bramka (bez zmian) | quant.adapters.extended |
| `rule:risk_engine` | risk_engine | RULE_OR_MEASUREMENT | STATE / state | – | IMPLEMENTED | NOT_EVALUATED (liczone z bieżących świec – stan tylko przy działającym bocie) | NOT_APPLICABLE | istniejąca bramka (bez zmian) | NOT_APPLICABLE: bramka ryzyka liczona w ścieżce wykonania (RiskBook / risk/portfolio.py) – Quant jej nie dubluje |
| `rule:news` | news | RULE_OR_MEASUREMENT | STATE / state | – | IMPLEMENTED | NOT_EVALUATED (liczone z bieżących świec – stan tylko przy działającym bocie) | NOT_APPLICABLE | istniejąca bramka (bez zmian) | quant.adapters.extended |
| `rule:regime_v2` | regime_v2 | RULE_OR_MEASUREMENT | STATE / state | M5, M15, H1 | IMPLEMENTED | NOT_EVALUATED (liczone z bieżących świec – stan tylko przy działającym bocie) | NOT_APPLICABLE | cecha kontekstu meta-modelu (z maską braku) | quant.adapters.extended |
| `rule:structure_v2` | structure_v2 | RULE_OR_MEASUREMENT | STATE / state | M5, M15, H1 | IMPLEMENTED | NOT_EVALUATED (liczone z bieżących świec – stan tylko przy działającym bocie) | NOT_APPLICABLE | stan kontekstu (panel / agent) – bez cech meta-modelu | quant.adapters.extended |
| `rule:smc_pullback` | smc_pullback | RULE_OR_MEASUREMENT | – | – | IMPLEMENTED | NOT_EVALUATED (liczone z bieżących świec – stan tylko przy działającym bocie) | NOT_APPLICABLE | cecha kontekstu meta-modelu (z maską braku) | NOT_APPLICABLE: akcesor istnieje: migawka SH sh.snapshot['ctx'] w każdym cyklu SH (smc_trend_m5, smc_high_m5 / smc_low_m5, pb_last_high_m5 / pb_last_low_m5, smc_trend_m1 / smc_last_m1); brak adaptera Quant – nie jest cechą MetaModelu (PMW-P |
| `rule:vamd` | vamd | RULE_OR_MEASUREMENT | – | – | IMPLEMENTED | NOT_EVALUATED (liczone z bieżących świec – stan tylko przy działającym bocie) | NOT_APPLICABLE | cecha kontekstu meta-modelu (z maską braku) | NOT_APPLICABLE: VAMD liczony na żywo w migawce SH (sh.context: ctx.vamd_m5 / ctx.vamd_m1) i per wykres w context_ind (panel); bez adaptera Quant (PMW-PRED-2) – nie jest modelem „Quant Ultimate Momentum Pro” |
| `rule:fractal` | fractal | RULE_OR_MEASUREMENT | – | – | IMPLEMENTED | NOT_EVALUATED (liczone z bieżących świec – stan tylko przy działającym bocie) | NOT_APPLICABLE | cecha kontekstu meta-modelu (z maską braku) | NOT_APPLICABLE: Katz FD liczony na żywo w migawce SH (sh.context: ctx.fd_zone_m5) i per wykres w context_ind; bez adaptera Quant (PMW-PRED-2) |
| `rule:atr_vol` | atr_vol | RULE_OR_MEASUREMENT | STATE / price | M1, M5 | IMPLEMENTED | NOT_EVALUATED (liczone z bieżących świec – stan tylko przy działającym bocie) | NOT_APPLICABLE | cecha kontekstu meta-modelu (z maską braku) | quant.adapters.extended |
| `rule:candles_patterns` | candles_patterns | RULE_OR_MEASUREMENT | – | – | IMPLEMENTED | NOT_EVALUATED (liczone z bieżących świec – stan tylko przy działającym bocie) | NOT_APPLICABLE | cecha kontekstu meta-modelu (z maską braku) | NOT_APPLICABLE: formacje opisowe (role świec) – kontekst panelu, bez liczbowego wyjścia |
| `rule:liquidity` | liquidity | RULE_OR_MEASUREMENT | – | – | IMPLEMENTED | NOT_EVALUATED (liczone z bieżących świec – stan tylko przy działającym bocie) | NOT_APPLICABLE | cecha kontekstu meta-modelu (z maską braku) | NOT_APPLICABLE: poziomy płynności (boksy sesji / sweep – analytics.session_engine, heatmapa likwidacji – analytics.liquidation) w polityce OBSERVE analytics.liquidity_context (panel, kontekst silnika, agent); brak adaptera Quant i brak cech |
| `rule:flow_sr` | flow_sr | RULE_OR_MEASUREMENT | – | – | IMPLEMENTED | NOT_EVALUATED (liczone z bieżących świec – stan tylko przy działającym bocie) | NOT_APPLICABLE | cecha kontekstu meta-modelu (z maską braku) | NOT_APPLICABLE: pasma S/R flow_context per wykres – bez akcesora snapshotu |
| `rule:decomposition` | decomposition | RULE_OR_MEASUREMENT | – | – | IMPLEMENTED | NOT_EVALUATED (liczone z bieżących świec – stan tylko przy działającym bocie) | NOT_APPLICABLE | cecha kontekstu meta-modelu (z maską braku) | NOT_APPLICABLE: obserwacja cyklu (FFT/EMD/VMD) – brak zadania predykcyjnego |
| `sh:tp_model` | sh_tp_model | MODEL_TRAINED | EVENT_PROBABILITY / TP2_BEFORE_SL_H / probability | – | IMPLEMENTED | NOT_TRAINED (SCALPING: brak modelu zdarzenia – uruchom trening sh_models (panel Trening / runner); HEDGING: brak modelu zdarzenia – uruchom trening sh_models (panel Trening / runner)) | NOT_VALIDATED | prawdopodobieństwo zdarzenia setupu (ewaluacja) | evaluation.service (prawdopodobieństwo per kandydat setupu) |
| `scalp:A_direction` | scalp_A | MODEL_TRAINED | CLASS_PROBABILITIES / SCALP_DIRECTION_H1_3_5M / probability | M1 | IMPLEMENTED | NOT_TRAINED (brak rejestru registry.json (zadanie treningu nie zostało uruchomione na danych)) | NOT_VALIDATED | prognoza bazowa – cecha meta-modelu pod własną nazwą | quant.adapters.extended |
| `scalp:B_setup_quality` | scalp_B | MODEL_TRAINED | EVENT_PROBABILITY / probability | M1 | IMPLEMENTED | NOT_TRAINED (brak rejestru registry.json (zadanie treningu nie zostało uruchomione na danych)) | NOT_VALIDATED | prawdopodobieństwo zdarzenia setupu (ewaluacja) | NOT_APPLICABLE: P(TP1 przed SL) INNEGO setupu (Range→Sweep→Retest) – liczony tylko dla planu scalp; brak modelu z replayu na danych rzeczywistych |
| `forecast:gold_candles` | gold_candles, gold_candles_15m, gold_candles_30m, gold_candles_5m, gold_forecast | MODEL_TRAINED | CLASS_PROBABILITIES / CANDLE_CLOSE_DIRECTION_H*_M5 / probability | M5; 1/3/6 świec M5 (5/15/30 min) | IMPLEMENTED | NOT_TRAINED (brak rejestru registry.json (zadanie treningu nie zostało uruchomione na danych)) | NOT_VALIDATED | prognoza bazowa – cecha meta-modelu pod własną nazwą | modelhub.adapters.all_predictions |
| `ml:legacy_s01_s12` | legacy_ml | MODEL_TRAINED | EVENT_PROBABILITY / NET_R_POSITIVE_S01_S12 / probability | – | IMPLEMENTED | UNAVAILABLE (instrument inny niż aktywny w bocie) | NOT_VALIDATED | prawdopodobieństwo zdarzenia setupu (ewaluacja) | evaluation.service (prawdopodobieństwo per kandydat setupu) |
| `group:lab` | – | GROUP | – | – | GROUP | NOT_EVALUATED | NOT_APPLICABLE | brak (nie istnieje) | NOT_APPLICABLE: wiersz grupowy – rozwinięty na rzeczywiste rodziny: lab:DUMMY, lab:RULE, lab:LOGREG, lab:TREE, lab:MINIROCKET, lab:XGB, lab:RESNET1D, lab:SEW_SNN, lab:LOGREG_PCA, lab:LOGREG_GMM_AUG, lab:LOGREG_NEUTRALIZED |
| `extind:indicator_context` | indicator_context | MODEL_TRAINED | SCORE / probability | – | IMPLEMENTED | NOT_TRAINED (brak rejestru registry.json (zadanie treningu nie zostało uruchomione na danych)) | NOT_VALIDATED | prawdopodobieństwo zdarzenia setupu (ewaluacja) | NOT_APPLICABLE: score polityki scalp (TP1 przed SL innego planu) – liczony per plan w scalp.indicator_context |
| `ml_scalp:xgb_net_r` | ml_scalp | MODEL_TRAINED | EVENT_PROBABILITY / probability | – | IMPLEMENTED | NOT_TRAINED (brak rejestru registry.json (zadanie treningu nie zostało uruchomione na danych)) | NOT_VALIDATED | prawdopodobieństwo zdarzenia setupu (ewaluacja) | NOT_APPLICABLE: P(net R>0) innego cyklu scalp – liczony per plan w scalp.ml_scalp |
| `nss:tcn` | nss | MODEL_TRAINED | CLASS_PROBABILITIES / probability | – | IMPLEMENTED | NOT_TRAINED (brak rejestru registry.json (zadanie treningu nie zostało uruchomione na danych)) | NOT_VALIDATED | prawdopodobieństwo zdarzenia setupu (ewaluacja) | NOT_APPLICABLE: P(TP1_FIRST/SL_FIRST/TIMEOUT) innego setupu – liczony per plan w scalp.neural |
| `group:si_move` | – | GROUP | – | – | GROUP | NOT_EVALUATED | NOT_APPLICABLE | brak (nie istnieje) | NOT_APPLICABLE: wiersz grupowy – rozwinięty na rzeczywiste rodziny: si:MQ_RESNEXT1D_V2, si:MQ_SEW_RESNET1D_V2, si:MQ_SEW_RESNEXT_EB_V1, si:MQ_MINIROCKET_RIDGE_V2, si:MQ_SPIKE_BRAIN_FINANCE_V1 |
| `flow:reaction_m1` | flow_reaction | MODEL_TRAINED | CLASS_PROBABILITIES / probability | M1 | IMPLEMENTED | NOT_TRAINED (brak runów modelu reakcji (zadanie flow_context nie było uruchomione na danych)) | NOT_VALIDATED | prognoza bazowa – cecha meta-modelu pod własną nazwą | NOT_APPLICABLE: NOT_CONNECTED: model reakcji FLOW_CONTEXT_MOVE_M1_V1 trenowany (LOGREG / XGB), bez ścieżki inferencji na żywo – FlowSections liczy tylko Heikin / S-R / StopDistance i Markov3 (flow:markov3); replay tylko z CLI (F-17) |
| `context_ind:context_move_m5` | CONTEXT_MOVE_M5_V1, context_move | MODEL_TRAINED | CLASS_PROBABILITIES / probability | M5 | IMPLEMENTED | NOT_CONNECTED (0 runów; model bez ścieżki inferencji na żywo (F-17) – tylko badania) | NOT_VALIDATED | prognoza bazowa – cecha meta-modelu pod własną nazwą | NOT_APPLICABLE: NOT_CONNECTED: model badawczy bez ścieżki inferencji na żywo (F-17) |
| `mm:align_mean` | align_mean, mm_align_mean | RULE_OR_MEASUREMENT | STATE / mixed | – | IMPLEMENTED | NOT_EVALUATED (liczone z bieżących świec – stan tylko przy działającym bocie) | NOT_APPLICABLE | stan kontekstu (panel / agent) – bez cech meta-modelu | quant.adapters.extended |
| `mm:kalman_cross` | kalman, mm_kalman | RULE_OR_MEASUREMENT | FILTER_STATE / state | M5 | IMPLEMENTED | NOT_EVALUATED (liczone z bieżących świec – stan tylko przy działającym bocie) | NOT_APPLICABLE | cecha kontekstu meta-modelu (z maską braku) | quant.adapters.extended |
| `mm:breakout_zones` | breakout_zones, mm_breakout | RULE_OR_MEASUREMENT | FILTER_STATE / state | M5 | IMPLEMENTED | NOT_EVALUATED (liczone z bieżących świec – stan tylko przy działającym bocie) | NOT_APPLICABLE | cecha kontekstu meta-modelu (z maską braku) | quant.adapters.extended |
| `mm:multi_indicator` | mm_multi_indicator, multi_indicator | RULE_OR_MEASUREMENT | STATE / state | M5 | IMPLEMENTED | NOT_EVALUATED (liczone z bieżących świec – stan tylko przy działającym bocie) | NOT_APPLICABLE | stan kontekstu (panel / agent) – bez cech meta-modelu | quant.adapters.extended |
| `mm:smc_fvg` | mm_smc_fvg, smc_fvg | RULE_OR_MEASUREMENT | STATE / state | M5 | IMPLEMENTED | NOT_EVALUATED (liczone z bieżących świec – stan tylko przy działającym bocie) | NOT_APPLICABLE | stan kontekstu (panel / agent) – bez cech meta-modelu | quant.adapters.extended |
| `mm:gpr_logret` | gpr, gpr_logret, gpr_logret:LIVE, mm_gpr | MODEL_TRAINED | REGRESSION / LOG_RETURN_H3_M5 / log_return | M5; 3 świece M5 | IMPLEMENTED | NOT_EVALUATED (liczone z bieżących świec – stan tylko przy działającym bocie) | NOT_VALIDATED | prognoza bazowa – cecha meta-modelu pod własną nazwą | quant.adapters.extended |
| `mm:hdc_dir3` | hdc, hdc_dir3, mm_hdc | MODEL_TRAINED | SCORE / ratio | M5 | IMPLEMENTED | NOT_TRAINED (brak artefaktu – zadanie treningu master_models nie było uruchomione) | NOT_VALIDATED | prognoza bazowa – cecha meta-modelu pod własną nazwą | NOT_APPLICABLE: margines HDC (nie prawdopodobieństwo); brak ścieżki na żywo bez artefaktu VALIDATED_SHADOW |
| `mm:event_engine_dir3` | SEQ_GRU_EVENT, event_engine, event_engine_dir3, family:SEQ_GRU_EVENT, mm_event_engine | MODEL_TRAINED | CLASS_PROBABILITIES / EVENT_UNITS_DIR3 / probability | EVENT; 2 jednostki zdarzeń (16 zdarzeń/jednostka) | IMPLEMENTED | NOT_TRAINED (brak artefaktu – zadanie treningu master_models nie było uruchomione) | NOT_VALIDATED | prognoza bazowa – cecha meta-modelu pod własną nazwą | quant.adapters.extended |
| `mm:ste_flownet_ret` | mm_ste_flownet, ste_flownet, ste_flownet_ret | MODEL_TRAINED | REGRESSION / log_return | EVENT | IMPLEMENTED | NOT_TRAINED (brak artefaktu – zadanie treningu master_models nie było uruchomione) | NOT_VALIDATED | prognoza bazowa – cecha meta-modelu pod własną nazwą | NOT_APPLICABLE: brak ścieżki na żywo (tylko artefakt badawczy); log-zwrot h zdarzeń |
| `group:th_direction` | – | GROUP | – | – | GROUP | NOT_EVALUATED | NOT_APPLICABLE | brak (nie istnieje) | NOT_APPLICABLE: wiersz grupowy – rozwinięty na rzeczywiste rodziny: trainhub:TH_BASELINE, trainhub:TH_LOGREG, trainhub:TH_HGB, trainhub:TH_XGB, trainhub:TH_RF, trainhub:TH_SVM |
| `kronos:Kronos-small` | KRONOS_SMALL, Kronos-small, kronos | MODEL_PRETRAINED | REGRESSION / KRONOS_CLOSE_PATH_H* / price | M1, M3, M5, M15, M30, H1 | IMPLEMENTED | UNAVAILABLE (stan Kronos: osobny kontekst w ocenie setupu (su.kronos) i panel Kronos AI Forecast) | NOT_VALIDATED | prognoza bazowa – cecha meta-modelu pod własną nazwą | modelhub.adapters.all_predictions |
| `agent:claude` | agent | AGENT | STATE / state | – | IMPLEMENTED | SHADOW_ONLY (agent: ?; weto/opis, nie głos) | NOT_APPLICABLE | opis / opinia – bez p(win) | NOT_APPLICABLE: opis / weto tekstowe agenta – bez p(win); poza meta-modelem |
| `tsfm:chronos2` | CHRONOS2, Chronos-2, chronos2 | MODEL_PRETRAINED | REGRESSION / TSFM_CLOSE_H* / price | M1, M3, M5, M15, M30, H1 | IMPLEMENTED | UNAVAILABLE (serwis Chronos-2/Granite TTM/TiRex-2 niedostępny) | NOT_VALIDATED | prognoza bazowa – cecha meta-modelu pod własną nazwą | modelhub.adapters.all_predictions |
| `tsfm:granite_ttm` | GRANITE_TTM, Granite TTM, granite_ttm | MODEL_PRETRAINED | REGRESSION / TSFM_CLOSE_H* / price | M1, M3, M5, M15, M30, H1 | IMPLEMENTED | UNAVAILABLE (serwis Chronos-2/Granite TTM/TiRex-2 niedostępny) | NOT_VALIDATED | prognoza bazowa – cecha meta-modelu pod własną nazwą | modelhub.adapters.all_predictions |
| `tsfm:tirex2` | TIREX2, TiRex-2, tirex2 | MODEL_PRETRAINED | REGRESSION / TSFM_CLOSE_H* / price | M5, M15 | IMPLEMENTED | UNAVAILABLE (serwis Chronos-2/Granite TTM/TiRex-2 niedostępny) | NOT_VALIDATED | prognoza bazowa – cecha meta-modelu pod własną nazwą | modelhub.adapters.all_predictions |
| `trainhub:TH_BASELINE` | TH_BASELINE | MODEL_TRAINED | CLASS_PROBABILITIES / DIRECTION_H<h>_<TF> po kosztach / probability | M1, M5, M15, M30; h świec (per paczka) | IMPLEMENTED | NOT_TRAINED (brak paczki – trening w Centrum treningu) | NOT_VALIDATED | narzędzie / proces uczenia / optymalizacja – nie głos | modelhub.adapters.all_predictions |
| `trainhub:TH_LOGREG` | TH_LOGREG | MODEL_TRAINED | CLASS_PROBABILITIES / DIRECTION_H<h>_<TF> po kosztach / probability | M1, M5, M15, M30; h świec (per paczka) | IMPLEMENTED | NOT_TRAINED (brak paczki – trening w Centrum treningu) | NOT_VALIDATED | prognoza bazowa – cecha meta-modelu pod własną nazwą | modelhub.adapters.all_predictions |
| `trainhub:TH_HGB` | TH_HGB | MODEL_TRAINED | CLASS_PROBABILITIES / DIRECTION_H<h>_<TF> po kosztach / probability | M1, M5, M15, M30; h świec (per paczka) | IMPLEMENTED | NOT_TRAINED (brak paczki – trening w Centrum treningu) | NOT_VALIDATED | prognoza bazowa – cecha meta-modelu pod własną nazwą | modelhub.adapters.all_predictions |
| `trainhub:TH_XGB` | TH_XGB, family:TH_XGB | MODEL_TRAINED | CLASS_PROBABILITIES / DIRECTION_H<h>_<TF> po kosztach / probability | M1, M5, M15, M30; h świec (per paczka) | IMPLEMENTED | NOT_TRAINED (brak paczki – trening w Centrum treningu) | NOT_VALIDATED | prognoza bazowa – cecha meta-modelu pod własną nazwą | modelhub.adapters.all_predictions |
| `trainhub:TH_RF` | TH_RF, family:TH_RF | MODEL_TRAINED | CLASS_PROBABILITIES / DIRECTION_H<h>_<TF> po kosztach / probability | M1, M5, M15, M30; h świec (per paczka) | IMPLEMENTED | NOT_TRAINED (brak paczki – trening w Centrum treningu) | NOT_VALIDATED | prognoza bazowa – cecha meta-modelu pod własną nazwą | modelhub.adapters.all_predictions |
| `trainhub:TH_SVM` | TH_SVM, family:TH_SVM | MODEL_TRAINED | CLASS_PROBABILITIES / DIRECTION_H<h>_<TF> po kosztach / probability | M1, M5, M15, M30; h świec (per paczka) | IMPLEMENTED | NOT_TRAINED (brak paczki – trening w Centrum treningu) | NOT_VALIDATED | prognoza bazowa – cecha meta-modelu pod własną nazwą | modelhub.adapters.all_predictions |
| `family:TS_ARIMA` | TS_ARIMA | MODEL_TRAINED | REGRESSION / LOG_RETURN_H / log_return | M5; [1, 3, 5] świec M5 | IMPLEMENTED | NOT_EVALUATED | NOT_VALIDATED | prognoza bazowa – cecha meta-modelu pod własną nazwą | modelhub.families.service.predictions |
| `family:TS_SARIMAX` | TS_SARIMAX | MODEL_TRAINED | REGRESSION / LOG_RETURN_H / log_return | H1; [1, 3, 5] świec H1 | IMPLEMENTED | NOT_EVALUATED | NOT_VALIDATED | prognoza bazowa – cecha meta-modelu pod własną nazwą | modelhub.families.service.predictions |
| `family:VOL_GARCH` | VOL_GARCH | MODEL_TRAINED | VOLATILITY / SIGMA_LOG_RETURN_H / sigma_return | M5; [1, 6, 12] świec M5 | IMPLEMENTED | NOT_EVALUATED | NOT_VALIDATED | prognoza bazowa – cecha meta-modelu pod własną nazwą | modelhub.families.service.predictions |
| `family:MICROSTRUCTURE` | MICROSTRUCTURE | MEASUREMENT | MICROSTRUCTURE / BOOK_STATE_AND_REACTION_10S / mixed | –; brak (pomiar stanu) | IMPLEMENTED | NOT_EVALUATED | NOT_VALIDATED | cecha kontekstu meta-modelu (z maską braku) | modelhub.families.service.predictions |
| `family:PAIR_COINT` | PAIR_COINT | MODEL_TRAINED | PAIR_RELATION / PAIR_SPREAD_Z / z_score | H1; [1] świec H1 | IMPLEMENTED | NOT_EVALUATED | NOT_VALIDATED | cecha kontekstu meta-modelu (z maską braku) | modelhub.families.service.predictions |
| `family:STATARB` | STATARB | MODEL_TRAINED | PAIR_RELATION / BASKET_RESIDUAL_S / z_score | H1; [1] świec H1 | IMPLEMENTED | NOT_EVALUATED | NOT_VALIDATED | cecha kontekstu meta-modelu (z maską braku) | modelhub.families.service.predictions |
| `family:KALMAN_LS` | KALMAN_LS | MODEL_ESTIMATED | FILTER_STATE / TREND_STATE / mixed | M5; [1] świec M5 | IMPLEMENTED | NOT_EVALUATED | NOT_VALIDATED | cecha kontekstu meta-modelu (z maską braku) | modelhub.families.service.predictions |
| `family:BREAKOUT` | BREAKOUT | MODEL_ESTIMATED | FILTER_STATE / BREAKOUT_STATE / mixed | M5; [1] świec M5 | IMPLEMENTED | NOT_EVALUATED | NOT_VALIDATED | cecha kontekstu meta-modelu (z maską braku) | modelhub.families.service.predictions |
| `family:SEQ_LSTM` | SEQ_LSTM | MODEL_TRAINED | CLASS_PROBABILITIES / DIRECTION_H6_AFTER_COST / probability | M5; [6] świec M5 | IMPLEMENTED | MISSING_DEPENDENCY (brak środowiska .venv_deep (instalacja: 34_DEEP_INSTALUJ.bat)) | NOT_VALIDATED | prognoza bazowa – cecha meta-modelu pod własną nazwą | modelhub.families.service.predictions |
| `family:SEQ_GRU` | SEQ_GRU | MODEL_TRAINED | CLASS_PROBABILITIES / DIRECTION_H6_AFTER_COST / probability | M5; [6] świec M5 | IMPLEMENTED | MISSING_DEPENDENCY (brak środowiska .venv_deep (instalacja: 34_DEEP_INSTALUJ.bat)) | NOT_VALIDATED | prognoza bazowa – cecha meta-modelu pod własną nazwą | modelhub.families.service.predictions |
| `family:RL_PPO` | RL_PPO | MODEL_TRAINED | RL_ACTION / TARGET_EXPOSURE / action | M5; brak (pomiar stanu) | IMPLEMENTED | MISSING_DEPENDENCY (brak środowiska .venv_deep (instalacja: 34_DEEP_INSTALUJ.bat)) | NOT_VALIDATED | opis / opinia – bez p(win) | modelhub.families.service.predictions |
| `family:NLP_SENTIMENT` | NLP_SENTIMENT | MODEL_TRAINED | NLP_SENTIMENT / TEXT_SENTIMENT_3 / sentiment | –; brak (pomiar stanu) | IMPLEMENTED | NOT_EVALUATED | NOT_VALIDATED | cecha kontekstu meta-modelu (z maską braku) | modelhub.families.service.predictions |
| `lab:DUMMY` | – | BASELINE | SCORE / TRIPLE_BARRIER_1.5ATR_LONG (score nieskalibrowany) / ratio | M5 | IMPLEMENTED | NOT_EVALUATED | NOT_VALIDATED | narzędzie / proces uczenia / optymalizacja – nie głos | quant.adapters.extended |
| `lab:RULE` | – | BASELINE | SCORE / TRIPLE_BARRIER_1.5ATR_LONG (score nieskalibrowany) / ratio | M5 | IMPLEMENTED | NOT_EVALUATED | NOT_VALIDATED | narzędzie / proces uczenia / optymalizacja – nie głos | quant.adapters.extended |
| `lab:LOGREG` | – | MODEL_TRAINED | SCORE / TRIPLE_BARRIER_1.5ATR_LONG (score nieskalibrowany) / ratio | M5 | IMPLEMENTED | NOT_EVALUATED | NOT_VALIDATED | prognoza bazowa – cecha meta-modelu pod własną nazwą | quant.adapters.extended |
| `lab:TREE` | – | MODEL_TRAINED | SCORE / TRIPLE_BARRIER_1.5ATR_LONG (score nieskalibrowany) / ratio | M5 | IMPLEMENTED | NOT_EVALUATED | NOT_VALIDATED | prognoza bazowa – cecha meta-modelu pod własną nazwą | quant.adapters.extended |
| `lab:MINIROCKET` | – | MODEL_TRAINED | SCORE / TRIPLE_BARRIER_1.5ATR_LONG (score nieskalibrowany) / ratio | M5 | IMPLEMENTED | NOT_EVALUATED | NOT_VALIDATED | prognoza bazowa – cecha meta-modelu pod własną nazwą | quant.adapters.extended |
| `lab:XGB` | – | MODEL_TRAINED | SCORE / TRIPLE_BARRIER_1.5ATR_LONG (score nieskalibrowany) / ratio | M5 | IMPLEMENTED | NOT_EVALUATED | NOT_VALIDATED | prognoza bazowa – cecha meta-modelu pod własną nazwą | quant.adapters.extended |
| `lab:RESNET1D` | – | MODEL_TRAINED | SCORE / TRIPLE_BARRIER_1.5ATR_LONG (score nieskalibrowany) / ratio | M5 | IMPLEMENTED | NOT_EVALUATED | NOT_VALIDATED | prognoza bazowa – cecha meta-modelu pod własną nazwą | quant.adapters.extended |
| `lab:SEW_SNN` | – | MODEL_TRAINED | SCORE / TRIPLE_BARRIER_1.5ATR_LONG (score nieskalibrowany) / ratio | M5 | IMPLEMENTED | NOT_EVALUATED | NOT_VALIDATED | prognoza bazowa – cecha meta-modelu pod własną nazwą | quant.adapters.extended |
| `lab:LOGREG_PCA` | – | RESEARCH | SCORE / TRIPLE_BARRIER_1.5ATR_LONG (score nieskalibrowany) / ratio | M5 | IMPLEMENTED | NOT_EVALUATED | NOT_VALIDATED | prognoza bazowa – cecha meta-modelu pod własną nazwą | quant.adapters.extended |
| `lab:LOGREG_GMM_AUG` | – | RESEARCH | SCORE / TRIPLE_BARRIER_1.5ATR_LONG (score nieskalibrowany) / ratio | M5 | IMPLEMENTED | NOT_EVALUATED | NOT_VALIDATED | prognoza bazowa – cecha meta-modelu pod własną nazwą | quant.adapters.extended |
| `lab:LOGREG_NEUTRALIZED` | – | RESEARCH | SCORE / TRIPLE_BARRIER_1.5ATR_LONG (score nieskalibrowany) / ratio | M5 | IMPLEMENTED | NOT_EVALUATED | NOT_VALIDATED | prognoza bazowa – cecha meta-modelu pod własną nazwą | quant.adapters.extended |
| `si:MQ_RESNEXT1D_V2` | – | MODEL_TRAINED | CLASS_PROBABILITIES / M1_MOVE_H3/5/15 (DOWN/FLAT/UP + kwantyle r_h/ATR) / probability | M1 | IMPLEMENTED | NOT_EVALUATED | NOT_VALIDATED | prognoza bazowa – cecha meta-modelu pod własną nazwą | NOT_APPLICABLE: prognoza SHADOW STRUCTURE_MOVE_M1_V1 liczona na żywo przy każdej zamkniętej M1 (scalp.service -> scalp.dashboard (MTF) -> lab.si_service.forecast) tylko dla rodziny wskazanej w rejestrze SI shadow[STRUCTURE_MOVE_M1_V1]; arch |
| `si:MQ_SEW_RESNET1D_V2` | – | MODEL_TRAINED | CLASS_PROBABILITIES / M1_MOVE_H3/5/15 (DOWN/FLAT/UP + kwantyle r_h/ATR) / probability | M1 | IMPLEMENTED | NOT_EVALUATED | NOT_VALIDATED | prognoza bazowa – cecha meta-modelu pod własną nazwą | NOT_APPLICABLE: prognoza SHADOW STRUCTURE_MOVE_M1_V1 liczona na żywo przy każdej zamkniętej M1 (scalp.service -> scalp.dashboard (MTF) -> lab.si_service.forecast) tylko dla rodziny wskazanej w rejestrze SI shadow[STRUCTURE_MOVE_M1_V1]; arch |
| `si:MQ_SEW_RESNEXT_EB_V1` | – | MODEL_TRAINED | CLASS_PROBABILITIES / M1_MOVE_H3/5/15 (DOWN/FLAT/UP + kwantyle r_h/ATR) / probability | M1 | IMPLEMENTED | NOT_EVALUATED | NOT_VALIDATED | prognoza bazowa – cecha meta-modelu pod własną nazwą | NOT_APPLICABLE: prognoza SHADOW STRUCTURE_MOVE_M1_V1 liczona na żywo przy każdej zamkniętej M1 (scalp.service -> scalp.dashboard (MTF) -> lab.si_service.forecast) tylko dla rodziny wskazanej w rejestrze SI shadow[STRUCTURE_MOVE_M1_V1]; arch |
| `si:MQ_MINIROCKET_RIDGE_V2` | – | MODEL_TRAINED | CLASS_PROBABILITIES / M1_MOVE_H3/5/15 (DOWN/FLAT/UP + kwantyle r_h/ATR) / probability | M1 | IMPLEMENTED | NOT_EVALUATED | NOT_VALIDATED | prognoza bazowa – cecha meta-modelu pod własną nazwą | NOT_APPLICABLE: prognoza SHADOW STRUCTURE_MOVE_M1_V1 liczona na żywo przy każdej zamkniętej M1 (scalp.service -> scalp.dashboard (MTF) -> lab.si_service.forecast) tylko dla rodziny wskazanej w rejestrze SI shadow[STRUCTURE_MOVE_M1_V1]; arch |
| `si:MQ_SPIKE_BRAIN_FINANCE_V1` | – | MODEL_TRAINED | CLASS_PROBABILITIES / M1_MOVE_H3/5/15 (DOWN/FLAT/UP + kwantyle r_h/ATR) / probability | M1 | IMPLEMENTED | NOT_EVALUATED | NOT_VALIDATED | prognoza bazowa – cecha meta-modelu pod własną nazwą | NOT_APPLICABLE: prognoza SHADOW STRUCTURE_MOVE_M1_V1 liczona na żywo przy każdej zamkniętej M1 (scalp.service -> scalp.dashboard (MTF) -> lab.si_service.forecast) tylko dla rodziny wskazanej w rejestrze SI shadow[STRUCTURE_MOVE_M1_V1]; arch |
| `mm:buzoa` | – | OPTIMIZER | – | – | IMPLEMENTED | NOT_EVALUATED | NOT_APPLICABLE | narzędzie / proces uczenia / optymalizacja – nie głos | NOT_APPLICABLE: narzędzie / infrastruktura / proces uczenia – nie osobny głos modelu |
| `mm:sdom` | – | NO_SPEC | – | – | NO_SPEC | UNAVAILABLE (NO_SPEC) | NOT_APPLICABLE | narzędzie / proces uczenia / optymalizacja – nie głos | NOT_APPLICABLE: brak specyfikacji w paczce – algorytm nie jest odtwarzany z nazwy |
| `mm:stfs` | – | TRAINABLE | – | – | IMPLEMENTED | NOT_EVALUATED | NOT_VALIDATED | narzędzie / proces uczenia / optymalizacja – nie głos | NOT_APPLICABLE: narzędzie / infrastruktura / proces uczenia – nie osobny głos modelu |
| `mm:quant_momentum` | – | NO_SPEC | – | – | NO_SPEC | UNAVAILABLE (NO_SPEC) | NOT_APPLICABLE | brak (nie istnieje) | NOT_APPLICABLE: brak specyfikacji w paczce – algorytm nie jest odtwarzany z nazwy |
| `mm:renko` | – | NO_SPEC | – | – | NO_SPEC | UNAVAILABLE (NO_SPEC) | NOT_APPLICABLE | brak (nie istnieje) | NOT_APPLICABLE: brak specyfikacji w paczce – algorytm nie jest odtwarzany z nazwy |
| `mm:head_shoulders` | – | NO_SPEC | – | – | NO_SPEC | UNAVAILABLE (NO_SPEC) | NOT_APPLICABLE | brak (nie istnieje) | NOT_APPLICABLE: brak specyfikacji w paczce – algorytm nie jest odtwarzany z nazwy |
| `mm:data_grabber` | – | NO_SPEC | – | – | NO_SPEC | UNAVAILABLE (NO_SPEC) | NOT_APPLICABLE | narzędzie / proces uczenia / optymalizacja – nie głos | NOT_APPLICABLE: brak specyfikacji w paczce – algorytm nie jest odtwarzany z nazwy |
| `mm:tsvp` | – | VISUALIZATION | – | – | IMPLEMENTED | NOT_EVALUATED | NOT_APPLICABLE | narzędzie / proces uczenia / optymalizacja – nie głos | NOT_APPLICABLE: narzędzie / infrastruktura / proces uczenia – nie osobny głos modelu |
| `mm:mathbench` | – | BENCHMARK | – | – | IMPLEMENTED | NOT_EVALUATED | NOT_APPLICABLE | narzędzie / proces uczenia / optymalizacja – nie głos | NOT_APPLICABLE: narzędzie / infrastruktura / proces uczenia – nie osobny głos modelu |
| `mm:chart_sync` | – | NO_SPEC | – | – | NO_SPEC | UNAVAILABLE (NO_SPEC) | NOT_APPLICABLE | narzędzie / proces uczenia / optymalizacja – nie głos | NOT_APPLICABLE: brak specyfikacji w paczce – algorytm nie jest odtwarzany z nazwy |
| `mm:fusion_board` | – | DATA_INFRA | – | – | IMPLEMENTED | NOT_EVALUATED | NOT_APPLICABLE | narzędzie / proces uczenia / optymalizacja – nie głos | NOT_APPLICABLE: narzędzie / infrastruktura / proces uczenia – nie osobny głos modelu |
| `analysis:montecarlo` | – | SIMULATION | – | – | IMPLEMENTED | NOT_EVALUATED | NOT_VALIDATED | symulacja (MODEL_SIMULATED) – nie skalibrowane p | quant.adapters.extended |
| `analysis:zones` | – | ANALYSIS | – | – | IMPLEMENTED | NOT_EVALUATED | NOT_APPLICABLE | stan kontekstu (panel / agent) – bez cech meta-modelu | quant.adapters.extended |
| `analysis:market_zones` | – | ANALYSIS | – | – | IMPLEMENTED | NOT_EVALUATED | NOT_APPLICABLE | opis / opinia – bez p(win) | NOT_APPLICABLE: wizualizacja panelu Strefy rynkowe – liczone na żądanie (job) / w panelu, brak cyklu niezależnego od panelu; bez adaptera Quant i konsumenta cech |
| `analysis:indicators` | – | ANALYSIS | – | – | IMPLEMENTED | NOT_EVALUATED | NOT_APPLICABLE | stan kontekstu (panel / agent) – bez cech meta-modelu | quant.adapters.extended |
| `analysis:svp` | – | ANALYSIS | – | – | IMPLEMENTED | NOT_EVALUATED | NOT_APPLICABLE | istniejąca bramka (bez zmian) | NOT_APPLICABLE: profil poprzedniej sesji (svp.engine.compute na zamkniętych M5, tick volume = aktywność feedu, nie wolumen obrotu) jest warunkiem wejścia wariantów pakietu SH PMW_HG08 / PMW_SC10 (value_area_rejection: brak profilu = NO_DATA |
| `analysis:dxy_correlation` | – | ANALYSIS | – | – | IMPLEMENTED | NOT_EVALUATED | NOT_APPLICABLE | cecha kontekstu meta-modelu (z maską braku) | quant.adapters.extended |
| `analysis:walls` | – | ANALYSIS | – | – | IMPLEMENTED | NOT_EVALUATED | NOT_APPLICABLE | istniejąca bramka (bez zmian) | NOT_APPLICABLE: bez importu IV źródłem σ jest zmienność historyczna D1 (HV_PROXY, close-to-close), nie rynek opcji; IV_SOURCED niezaimplementowane (NOT_CONFIGURED); brak źródła = UNAVAILABLE, nie zero; poziomy ścian są wejściem strategii S1 |
| `analysis:evaluation` | – | ANALYSIS | – | – | IMPLEMENTED | NOT_EVALUATED | NOT_APPLICABLE | prawdopodobieństwo zdarzenia setupu (ewaluacja) | evaluation.service (ledger) |
| `quant:metamodel` | – | META_MODEL | – | – | IMPLEMENTED | NOT_EVALUATED | NOT_VALIDATED | Quant MetaModel | quant.service (assessment) |
| `ext:catboost` | – | NOT_IMPLEMENTED | – | – | NOT_IMPLEMENTED | UNAVAILABLE (wspomniany w dokumentacji / traceability (M06); brak implementacji i zależności w kodzie) | NOT_APPLICABLE | brak (nie istnieje) | NOT_APPLICABLE: nie istnieje w kodzie – nie dodano fikcyjnego adaptera |
| `quant:tabicl_v2` | – | MODEL_PRETRAINED | – | – | IMPLEMENTED | NOT_EVALUATED | NOT_VALIDATED | prawdopodobieństwo zdarzenia setupu (ewaluacja) | NOT_APPLICABLE: wynik per kandydat w pamięci QuantService (nieutrwalany) – brak samodzielnej predykcji |
| `flow:markov3` | – | MODEL_TRAINED | – | – | IMPLEMENTED | NOT_EVALUATED | NOT_VALIDATED | cecha kontekstu meta-modelu (z maską braku) | NOT_APPLICABLE: liczony w komórkach Structure Intelligence (panel) – bez adaptera Quant |
| `si:LOGREG` | – | MODEL_TRAINED | – | – | IMPLEMENTED | NOT_EVALUATED | NOT_VALIDATED | prognoza bazowa – cecha meta-modelu pod własną nazwą | NOT_APPLICABLE: rodzina bazowa SI – prognoza SHADOW STRUCTURE_MOVE_M1_V1 liczona na żywo przy każdej zamkniętej M1 (scalp.service -> scalp.dashboard (MTF) -> lab.si_service.forecast) tylko dla rodziny wskazanej w rejestrze SI shadow[STRUCTU |
| `si:XGB` | – | MODEL_TRAINED | – | – | IMPLEMENTED | NOT_EVALUATED | NOT_VALIDATED | prognoza bazowa – cecha meta-modelu pod własną nazwą | NOT_APPLICABLE: rodzina bazowa SI – prognoza SHADOW STRUCTURE_MOVE_M1_V1 liczona na żywo przy każdej zamkniętej M1 (scalp.service -> scalp.dashboard (MTF) -> lab.si_service.forecast) tylko dla rodziny wskazanej w rejestrze SI shadow[STRUCTU |
| `quotes:MQ_NEWTONIAN_QUOTES_V2` | – | RULE_OR_MEASUREMENT | – | – | IMPLEMENTED | NOT_EVALUATED | NOT_APPLICABLE | cecha kontekstu meta-modelu (z maską braku) | NOT_APPLICABLE: wątek si-quotes – stan panelu SI, bez adaptera Quant |
| `lab:M29_fourier` | – | RULE_OR_MEASUREMENT | – | – | IMPLEMENTED | NOT_EVALUATED | NOT_APPLICABLE | narzędzie / proces uczenia / optymalizacja – nie głos | NOT_APPLICABLE: archiwum lab_forecasts i ocena – obserwacja, nie głos |
| `lab:M31_tick_kinematics` | – | RULE_OR_MEASUREMENT | – | – | IMPLEMENTED | NOT_EVALUATED | NOT_APPLICABLE | narzędzie / proces uczenia / optymalizacja – nie głos | NOT_APPLICABLE: stan panelu lab – obserwacja |
| `lab:M42_trade_pad` | – | TOOL | – | – | IMPLEMENTED | NOT_EVALUATED | NOT_APPLICABLE | narzędzie / proces uczenia / optymalizacja – nie głos | NOT_APPLICABLE: kalkulator API na żądanie – nie model |
| `lab:M39_M41_edge` | – | TOOL | – | – | IMPLEMENTED | NOT_EVALUATED | NOT_APPLICABLE | narzędzie / proces uczenia / optymalizacja – nie głos | NOT_APPLICABLE: narzędzia diagnostyczne – nie głos |
| `research:graph50` | – | RESEARCH | – | – | IMPLEMENTED | NOT_EVALUATED | NOT_APPLICABLE | prognoza bazowa – cecha meta-modelu pod własną nazwą | modelhub.adapters.all_predictions |
| `research:g7_smc_radar` | – | RESEARCH | – | – | IMPLEMENTED | NOT_EVALUATED | NOT_APPLICABLE | cecha kontekstu meta-modelu (z maską braku) | modelhub.adapters.all_predictions |
| `research:sdformerflow` | – | RESEARCH | – | – | IMPLEMENTED | NOT_EVALUATED | NOT_APPLICABLE | prognoza bazowa – cecha meta-modelu pod własną nazwą | modelhub.adapters.all_predictions |
| `mm:kalman_params` | – | TRAINABLE | – | – | IMPLEMENTED | NOT_EVALUATED | NOT_VALIDATED | narzędzie / proces uczenia / optymalizacja – nie głos | NOT_APPLICABLE: kandydat parametrów – serwis używa domyślnej konfiguracji (brak ścieżki na żywo) |
| `mm:robust_vol` | – | RULE_OR_MEASUREMENT | – | – | IMPLEMENTED | NOT_EVALUATED | NOT_APPLICABLE | cecha kontekstu meta-modelu (z maską braku) | NOT_APPLICABLE: pole rekordu MM live – cechą Quant nie jest |
| `mm:drift` | – | RULE_OR_MEASUREMENT | – | – | IMPLEMENTED | NOT_EVALUATED | NOT_APPLICABLE | narzędzie / proces uczenia / optymalizacja – nie głos | NOT_APPLICABLE: pole rekordu MM live |
| `mm:bat_encoder` | – | RESEARCH | – | – | IMPLEMENTED | NOT_EVALUATED | NOT_APPLICABLE | opis / opinia – bez p(win) | NOT_APPLICABLE: tylko API /api/v1/models/bat/shadow; wagi niewytrenowane |
| `extind:sar_context` | – | RULE_OR_MEASUREMENT | – | – | IMPLEMENTED | NOT_EVALUATED | NOT_APPLICABLE | cecha kontekstu meta-modelu (z maską braku) | NOT_APPLICABLE: kontekst snapshotu ACTIVE / agenta – bez adaptera Quant |
| `extind:knowledge` | – | RULE_OR_MEASUREMENT | – | – | IMPLEMENTED | NOT_EVALUATED | NOT_APPLICABLE | opis / opinia – bez p(win) | NOT_APPLICABLE: opis dla agenta – nie głos |
| `extind:IQ_GOLD_GANN` | – | NATIVE_MQL5 | – | – | IMPLEMENTED | NOT_EVALUATED | NOT_APPLICABLE | cecha kontekstu meta-modelu (z maską braku) | NOT_APPLICABLE: natywny wskaźnik licencjonowany – działa tylko w terminalu MT5 |
| `extind:IQ_STAR_LINES` | – | NATIVE_MQL5 | – | – | IMPLEMENTED | NOT_EVALUATED | NOT_APPLICABLE | cecha kontekstu meta-modelu (z maską braku) | NOT_APPLICABLE: natywny wskaźnik licencjonowany – działa tylko w terminalu MT5 |
| `extind:PAL02M` | – | NO_SPEC | – | – | NO_SPEC | UNAVAILABLE (NO_SPEC) | NOT_APPLICABLE | brak (nie istnieje) | NOT_APPLICABLE: NO_SPEC: tożsamość narzędzia niepotwierdzona – algorytm nie jest odtwarzany z nazwy |
| `strategies:regime` | – | RULE_OR_MEASUREMENT | – | – | IMPLEMENTED | NOT_EVALUATED | NOT_APPLICABLE | istniejąca bramka (bez zmian) | NOT_APPLICABLE: bramka ścieżki A – Quant jej nie dubluje |
| `analysis:signals` | – | RULE_OR_MEASUREMENT | – | – | IMPLEMENTED | NOT_EVALUATED | NOT_APPLICABLE | istniejąca bramka (bez zmian) | NOT_APPLICABLE: warunki setupów ścieżki A (S12) – Quant ich nie dubluje |
| `analytics:session_engine` | – | RULE_OR_MEASUREMENT | – | – | IMPLEMENTED | NOT_EVALUATED | NOT_APPLICABLE | cecha kontekstu meta-modelu (z maską braku) | NOT_APPLICABLE: wejście rule:liquidity (OBSERVE) |
| `engine:volzones` | – | RULE_OR_MEASUREMENT | – | – | IMPLEMENTED | NOT_EVALUATED | NOT_APPLICABLE | opis / opinia – bez p(win) | NOT_APPLICABLE: tylko API / kontekst agenta |
| `apollo:market_trap` | – | RULE_OR_MEASUREMENT | – | – | IMPLEMENTED | NOT_EVALUATED | NOT_APPLICABLE | opis / opinia – bez p(win) | NOT_APPLICABLE: tylko GET /api/v1/market-trap |
| `baskets:sfb` | – | RULE_OR_MEASUREMENT | – | – | IMPLEMENTED | NOT_EVALUATED | NOT_APPLICABLE | istniejąca bramka (bez zmian) | NOT_APPLICABLE: filtr koszyków (domyślnie OFF) – Quant go nie dubluje |
| `ml:decision_tree_ranker` | – | MODEL_TRAINED | – | – | IMPLEMENTED | NOT_EVALUATED | NOT_VALIDATED | narzędzie / proces uczenia / optymalizacja – nie głos | NOT_APPLICABLE: nigdy nie trenowany w aplikacji – API zwraca FALLBACK_BASELINE |
| `ml:association_rules` | – | RULE_OR_MEASUREMENT | – | – | IMPLEMENTED | NOT_EVALUATED | NOT_APPLICABLE | opis / opinia – bez p(win) | NOT_APPLICABLE: tylko API (OBSERVE) |
| `ml:pt_directional_skill` | – | TOOL | – | – | IMPLEMENTED | NOT_EVALUATED | NOT_APPLICABLE | narzędzie / proces uczenia / optymalizacja – nie głos | NOT_APPLICABLE: miara trafności na danych wywołującego – nie model |
| `ml:change_point_engine` | – | RULE_OR_MEASUREMENT | – | – | IMPLEMENTED | NOT_EVALUATED | NOT_APPLICABLE | opis / opinia – bez p(win) | NOT_APPLICABLE: tylko API |
| `forecast:long_horizon` | – | RULE_OR_MEASUREMENT | – | – | IMPLEMENTED | NOT_EVALUATED | NOT_APPLICABLE | opis / opinia – bez p(win) | NOT_APPLICABLE: tylko API i eksport |
| `forecast:double_retest_v2` | – | RULE_OR_MEASUREMENT | – | – | IMPLEMENTED | NOT_EVALUATED | NOT_APPLICABLE | cecha kontekstu meta-modelu (z maską braku) | NOT_APPLICABLE: flagi w rekordzie prognozy – bez adaptera Quant |
| `scalp:C_policy` | – | TOOL | – | – | IMPLEMENTED | NOT_EVALUATED | NOT_APPLICABLE | narzędzie / proces uczenia / optymalizacja – nie głos | NOT_APPLICABLE: wynik replayu w rejestrze scalp – nie predykcja |

## Szczegóły (pliki, właściciele, środowiska, odbiorcy)

### `rule:data_quality` – Jakość i świeżość danych (bridge, zegar, spread)
* Pliki: `backend/masterquo/sh/context.py`, `backend/masterquo/data/quality.py`, `backend/masterquo/quant/snapshot.py`, `backend/masterquo/mt5/bridge.py`
* Wyjście: OK/BLOCK + wiek danych
* Wymagane dane: notowanie MT5, zegar, spread
* Środowisko: .venv
* Zależności: grupa korelacji DATA
* Odbiorcy: sh.service, engine.decision, quant.snapshot
* Rejestry źródłowe: sh.models.REGISTRY

### `rule:risk_engine` – Wspólny silnik ryzyka SH (limity, margin, spread, ekspozycja)
* Pliki: `backend/masterquo/sh/risk.py`, `backend/masterquo/risk/portfolio.py`
* Wyjście: PASS/BLOCK + powody
* Środowisko: .venv
* Zależności: grupa korelacji RISK
* Odbiorcy: SH:RISK_ANOMALY/RISK_ANOMALY
* Rejestry źródłowe: sh.models.REGISTRY

### `rule:news` – Kalendarz makro (blokada wysokiego wpływu)
* Pliki: `backend/masterquo/news/`
* Wyjście: blackout tak/nie
* Wymagane dane: kalendarz makro (czas pierwszego odbioru)
* Środowisko: .venv
* Zależności: grupa korelacji RISK
* Odbiorcy: SH:RISK_ANOMALY/RISK_ANOMALY
* Rejestry źródłowe: sh.models.REGISTRY

### `rule:regime_v2` – Reżim rynku MQ_REGIME_MULTI_V2 (market_v2)
* Wyjście: TREND_UP/TREND_DOWN/RANGE/TRANSITION (+ oś zmienności osobno)
* Środowisko: .venv
* Zależności: grupa korelacji REGIME
* Odbiorcy: SH:REGIME/REGIME
* Rejestry źródłowe: sh.models.REGISTRY

### `rule:structure_v2` – Struktura rynku structure_v2 (M5/M15/H1, BOS/CHoCH)
* Wyjście: trend per TF
* Środowisko: .venv
* Zależności: grupa korelacji STRUCTURE
* Odbiorcy: SH:DIRECTION_STRUCTURE/DIRECTION_STRUCTURE
* Rejestry źródłowe: sh.models.REGISTRY
* Uwagi: rekord STATE w migawce Quant (panel / agent / REQUIRED); quant/features.py nie buduje z niego cech – struktura nie jest wejściem MetaModelu (nowa cecha = osobna decyzja z nową wersją schematu cech)

### `rule:smc_pullback` – Pullback + SMC (BoS/CHoCH/IDM) – context_ind
* Wyjście: trend SMC, aktywne poziomy
* Środowisko: .venv
* Zależności: grupa korelacji STRUCTURE
* Odbiorcy: sh.setup (potwierdzenie odwrócenia: CHoCH M1 smc_last_m1), sh.context.obstacles (aktywne poziomy SMC M5 jako przeszkody przed TP), context_ind (panel)
* Rejestry źródłowe: sh.models.REGISTRY

### `rule:vamd` – VAMD momentum – profil DEFAULT (stały dla SH; kalibracja context_ind dotyczy panelu/badań)
* Wyjście: y (znak = momentum)
* Środowisko: .venv
* Zależności: grupa korelacji MOMENTUM
* Odbiorcy: sh.setup (warunek potwierdzenia CONTINUATION: znak vamd_m5), sh.tpmodel (cechy vamd_m5 / vamd_m1), context_ind (panel)
* Rejestry źródłowe: sh.models.REGISTRY
* Uwagi: dwie parametryzacje: SH = profil DEFAULT (zamrożony, sh/context.py), panel/SI = skalibrowany profil context_ind (profile_hash w odpowiedzi; panel pokazuje obok wartości DEFAULT używane przez SH)

### `rule:fractal` – Bounded Katz FD (trend/chop bez kierunku) – profil DEFAULT (stały dla SH; kalibracja context_ind dotyczy panelu/badań)
* Wyjście: TREND/NEUTRAL/CHOP
* Środowisko: .venv
* Zależności: grupa korelacji REGIME
* Odbiorcy: sh.setup (warunek potwierdzenia CONTINUATION: fd_zone_m5 ≠ CHOP), sh.tpmodel (cechy fd_trend / fd_chop z fd_zone_m5), context_ind (panel)
* Rejestry źródłowe: sh.models.REGISTRY
* Uwagi: dwie parametryzacje: SH = profil DEFAULT (zamrożony, sh/context.py), panel/SI = skalibrowany profil context_ind (profile_hash w odpowiedzi; panel pokazuje obok wartości DEFAULT używane przez SH)

### `rule:atr_vol` – Zmienność ATR(14) M1/M5 (sh/context, Wilder)
* Wyjście: ATR w USD
* Środowisko: .venv
* Zależności: grupa korelacji VOLATILITY
* Odbiorcy: SH:VOLATILITY/VOLATILITY
* Rejestry źródłowe: sh.models.REGISTRY

### `rule:candles_patterns` – Świece i formacje (candles, chart_patterns, sci2)
* Wyjście: rola świecy / formacja
* Środowisko: .venv
* Zależności: grupa korelacji PATTERN
* Odbiorcy: SH:PATTERN/PATTERN
* Rejestry źródłowe: sh.models.REGISTRY

### `rule:liquidity` – Płynność: sesje (sweep boxes) + heatmapa likwidacji
* Wyjście: poziomy płynności
* Środowisko: .venv
* Zależności: grupa korelacji LIQUIDITY
* Odbiorcy: SH:LIQUIDITY/LIQUIDITY
* Rejestry źródłowe: sh.models.REGISTRY

### `rule:flow_sr` – Heikin Flow + kanały S/R (flow_context)
* Wyjście: kolor HA, pasma S/R
* Środowisko: .venv
* Zależności: grupa korelacji STRUCTURE
* Odbiorcy: SH:DIRECTION_STRUCTURE/LIQUIDITY
* Rejestry źródłowe: sh.models.REGISTRY

### `rule:decomposition` – Dekompozycja sygnału FFT/EMD/VMD (analytics)
* Wyjście: cykl dominujący (obserwacja)
* Środowisko: .venv
* Zależności: grupa korelacji CYCLE
* Odbiorcy: SH:SUPERVISION/SUPERVISION
* Rejestry źródłowe: sh.models.REGISTRY

### `sh:tp_model` – SH: P(TP2 przed SL w horyzoncie) – model zdarzenia strategii
* Pliki: `backend/masterquo/sh/tpmodel.py`
* Wyjście: skalibrowane P dokładnie zdarzenia strategii
* Właściciel treningu: training (sh_models)
* Właściciel inferencji: sh.service
* Środowisko: .venv
* Zależności: grupa korelacji TP_EVENT_SH
* Odbiorcy: SH:TARGET_PROB/TARGET_PROB
* Rejestry źródłowe: sh.models.REGISTRY

### `scalp:A_direction` – Scalp A – kierunek 1/3/5 min (LR/HGB/MLP)
* Pliki: `backend/masterquo/scalp/service.py`
* Wyjście: P(DOWN/FLAT/UP) po kosztach
* Właściciel treningu: training (scalp_A)
* Właściciel inferencji: forecast worker (.venv_candles)
* Środowisko: .venv_candles
* Zależności: grupa korelacji M1_DIRECTION
* Odbiorcy: SH:DIRECTION_STRUCTURE/TIMING
* Rejestry źródłowe: sh.models.REGISTRY

### `scalp:B_setup_quality` – Scalp B – jakość setupu Range→Sweep→Retest
* Wyjście: P(TP1 przed SL) INNEGO setupu (score)
* Właściciel treningu: scalp_A
* Środowisko: .venv_candles
* Zależności: grupa korelacji TP_OTHER_EVENT
* Odbiorcy: SH:SUPERVISION/SUPERVISION
* Rejestry źródłowe: sh.models.REGISTRY

### `forecast:gold_candles` – gold_candles – prognoza świec 5/15/30 min
* Pliki: `backend/masterquo/forecast/`
* Wyjście: P(DOWN/FLAT/UP) zamknięcia
* Właściciel treningu: forecast
* Środowisko: .venv_candles
* Zależności: grupa korelacji M5_DIRECTION
* Odbiorcy: SH:TIMING/DIRECTION_STRUCTURE
* Rejestry źródłowe: sh.models.REGISTRY

### `ml:legacy_s01_s12` – Legacy ML Decision Tree + XGBoost (setupy S01–S12)
* Pliki: `backend/masterquo/ml/`
* Wyjście: P(net R > 0) setupu S01–S12
* Właściciel treningu: ml
* Środowisko: .venv
* Zależności: grupa korelacji TP_OTHER_EVENT
* Odbiorcy: SH:SUPERVISION/SUPERVISION
* Rejestry źródłowe: sh.models.REGISTRY

### `group:lab` – Lab: LOGREG/TREE/MiniRocket/XGB/ResNet1D/SEW-SNN
* Wyjście: score triple-barrier LONG (nieskalibrowany)
* Środowisko: .venv
* Warianty / członkowie: lab:DUMMY, lab:RULE, lab:LOGREG, lab:TREE, lab:MINIROCKET, lab:XGB, lab:RESNET1D, lab:SEW_SNN, lab:LOGREG_PCA, lab:LOGREG_GMM_AUG, lab:LOGREG_NEUTRALIZED
* Rejestry źródłowe: sh.models.REGISTRY

### `extind:indicator_context` – Kontekst wskaźników SAR + IQ (reakcja)
* Pliki: `backend/masterquo/extind/`
* Wyjście: P(TP1 przed SL) polityki scalp (score)
* Właściciel treningu: indicator_context
* Środowisko: .venv
* Zależności: grupa korelacji TP_OTHER_EVENT
* Odbiorcy: SH:SUPERVISION/SUPERVISION
* Rejestry źródłowe: sh.models.REGISTRY

### `ml_scalp:xgb_net_r` – Scalp ML XGBoost (net R cyklu)
* Pliki: `backend/masterquo/ml/scalp_task.py`, `backend/masterquo/ml/service.py`, `backend/masterquo/scalp/service.py`
* Wyjście: P(net_R > 0), E[net_R] innego cyklu
* Właściciel treningu: ml/scalp_task.py (training ml_scalp)
* Właściciel inferencji: ml.service.MLService.on_scalp_candidate (scalp.service)
* Środowisko: .venv
* Zależności: grupa korelacji TP_OTHER_EVENT
* Odbiorcy: SH:SUPERVISION/SUPERVISION
* Rejestry źródłowe: sh.models.REGISTRY

### `nss:tcn` – Neural Scalp System (TCN)
* Pliki: `backend/masterquo/lab/nss_service.py`
* Wyjście: P(TP1_FIRST/SL_FIRST/TIMEOUT) innego setupu
* Właściciel treningu: neural_scalp
* Środowisko: .venv
* Zależności: grupa korelacji TP_OTHER_EVENT
* Odbiorcy: SH:SUPERVISION/SUPERVISION
* Rejestry źródłowe: sh.models.REGISTRY

### `group:si_move` – Structure Intelligence – ruch M1 h=3/5/15 (ResNeXt/SEW/SpikingBrain/MiniRocket v2…)
* Wyjście: P(DOWN/FLAT/UP) + kwantyle r_h/ATR
* Środowisko: .venv
* Warianty / członkowie: si:MQ_RESNEXT1D_V2, si:MQ_SEW_RESNET1D_V2, si:MQ_SEW_RESNEXT_EB_V1, si:MQ_MINIROCKET_RIDGE_V2, si:MQ_SPIKE_BRAIN_FINANCE_V1
* Rejestry źródłowe: sh.models.REGISTRY

### `flow:reaction_m1` – Flow context – model reakcji M1 (FLOW_CONTEXT_MOVE_M1_V1)
* Pliki: `backend/masterquo/lab/flow_context/`
* Wyjście: P(DOWN/FLAT/UP) M1
* Właściciel treningu: flow_context
* Środowisko: .venv
* Zależności: grupa korelacji M1_DIRECTION
* Odbiorcy: SH:TIMING/TIMING
* Warianty / członkowie: flow:LOGREG, flow:XGB
* Rejestry źródłowe: sh.models.REGISTRY

### `context_ind:context_move_m5` – Context indicators – CONTEXT_MOVE_M5_V1
* Pliki: `backend/masterquo/lab/context_ind/`
* Wyjście: P(DOWN/FLAT/UP) M5
* Właściciel treningu: context_indicators
* Środowisko: .venv
* Zależności: grupa korelacji M5_DIRECTION
* Odbiorcy: SH:TIMING/DIRECTION_STRUCTURE
* Rejestry źródłowe: sh.models.REGISTRY

### `mm:align_mean` – Align Mean (wspólna średnia, odległość w ATR)
* Pliki: `backend/masterquo/mm/align_mean.py`, `mql5/MasterModels/Include/PMW/PMW_AlignMeanCore.mqh`, `mql5/MasterModels/Indicators/PMW_AlignMean.mq5`
* Wejście: closed OHLC (any TF)
* Wyjście: odległość od średniej (kontekst)
* Właściciel treningu: NOT_APPLICABLE
* Środowisko: .venv
* Zależności: grupa korelacji MM_MEAN_REF
* Odbiorcy: SH:OBSERVATION/OBSERVATION, mm.orchestrator:align_mean, mm.service (panel)
* Rejestry źródłowe: mm.inventory.MODULES, sh.models.REGISTRY
* Uwagi: odległości od średniej per TF (<TF>_dist_points / _dist_pct / _dist_atr: punkty, %, ATR) – rekord STATE bez cech MetaModelu

### `mm:kalman_cross` – Kalman crossover fast/slow (zamknięte świece)
* Pliki: `backend/masterquo/mm/kalman.py`, `mql5/MasterModels/Experts/PMW_KalmanShadowEA.mq5`, `mql5/MasterModels/Include/PMW/PMW_Kalman.mqh`, `mql5/MasterModels/Indicators/PMW_KalmanCross.mq5`
* Wejście: closed close
* Wyjście: stan przecięcia + K
* Właściciel treningu: NOT_APPLICABLE (state estimation; Q/R calibration = separate BUZOA job)
* Środowisko: .venv
* Zależności: grupa korelacji MM_TREND_FILTER
* Odbiorcy: SH:OBSERVATION/OBSERVATION, mm.orchestrator:kalman, mm.service
* Rejestry źródłowe: mm.inventory.MODULES, sh.models.REGISTRY

### `mm:breakout_zones` – Breakout zones + robust volatility
* Pliki: `backend/masterquo/mm/breakout_zones.py`, `backend/masterquo/mm/robust_vol.py`, `mql5/MasterModels/Include/PMW/PMW_BreakoutCore.mqh`, `mql5/MasterModels/Indicators/PMW_BreakoutZones.mq5`
* Wejście: closed OHLC + tick volume (VWAP proxy)
* Wyjście: kierunek ostatniego wybicia, strefy
* Właściciel treningu: NOT_APPLICABLE
* Środowisko: .venv
* Zależności: grupa korelacji MM_ZONES
* Odbiorcy: SH:OBSERVATION/OBSERVATION, mm.orchestrator:breakout, mm.service
* Rejestry źródłowe: mm.inventory.MODULES, sh.models.REGISTRY

### `mm:multi_indicator` – Multi-Indicator Strategy (RSI/SAR/HA/Stoch/CCI/W%R/Power)
* Pliki: `backend/masterquo/mm/multi_indicator.py`
* Wejście: closed OHLC (reuses scalp SAR + Wilder RSI)
* Wyjście: decyzja z pełnym śladem reguł
* Właściciel treningu: NOT_APPLICABLE
* Środowisko: .venv
* Zależności: grupa korelacji MM_RULES
* Odbiorcy: SH:OBSERVATION/OBSERVATION, mm.orchestrator:multi_indicator, mm.service
* Rejestry źródłowe: mm.inventory.MODULES, sh.models.REGISTRY

### `mm:smc_fvg` – SMC BoS/IDM/FVG continuation (głębokość cofnięcia 73% – parametr, nie skuteczność)
* Pliki: `backend/masterquo/lab/context_ind/smc.py (reused)`, `backend/masterquo/mm/smc_fvg.py`
* Wejście: closed OHLC
* Wyjście: setup entry/SL/2R (obserwacja)
* Właściciel treningu: NOT_APPLICABLE
* Środowisko: .venv
* Zależności: grupa korelacji STRUCTURE
* Odbiorcy: SH:OBSERVATION/OBSERVATION, mm.orchestrator:smc_fvg, mm.service
* Rejestry źródłowe: mm.inventory.MODULES, sh.models.REGISTRY

### `mm:gpr_logret` – GPR Matérn 3/2 – prognoza log-zwrotu z niepewnością
* Pliki: `backend/masterquo/mm/gpr.py`, `mql5/MasterModels/Experts/PMW_GPR_ShadowEA.mq5`, `mql5/MasterModels/Include/PMW/PMW_GPR.mqh`, `mql5/MasterModels/Indicators/PMW_GPR_Forecast.mq5`
* Wejście: lag-1 log return
* Wyjście: N(mean, observed var) log-zwrotu 3 świec M5
* Właściciel treningu: master_models
* Środowisko: .venv
* Zależności: grupa korelacji MM_RETURN_DIST
* Odbiorcy: SH:OBSERVATION/OBSERVATION, mm.orchestrator:gpr, mm.service
* Rejestry źródłowe: mm.inventory.MODULES, sh.models.REGISTRY

### `mm:hdc_dir3` – HDC – hiperwektory binarne (DOWN/FLAT/UP)
* Pliki: `backend/masterquo/mm/hdc.py`, `mql5/MasterModels/Include/PMW/PMW_HDC.mqh`
* Wejście: feature registry FS (M5)
* Wyjście: klasa + margines (nie prawdopodobieństwo)
* Właściciel treningu: master_models
* Środowisko: .venv
* Zależności: grupa korelacji M5_DIRECTION
* Odbiorcy: SH:OBSERVATION/OBSERVATION, mm.orchestrator:hdc, mm.service (tylko wskaźnik artefaktu, bez inferencji)
* Rejestry źródłowe: mm.inventory.MODULES, sh.models.REGISTRY
* Uwagi: margines podobieństwa: różnica podobieństw (1 − 2H/D) dwóch najlepszych klas, zakres 0..2 – nie skala 0–100, nie prawdopodobieństwo

### `mm:event_engine_dir3` – Event engine GRU + state stack + korelacja (+STFS)
* Pliki: `backend/masterquo/mm/event_engine.py`, `backend/masterquo/mm/events.py`, `backend/masterquo/mm/kernels/state_stack.cl`, `mql5/MasterModels/Include/PMW/PMW_StateStack.mqh`
* Wejście: REAL_TICKS (tick archive) or BAR_CLOSE_EVENTS adapter
* Wyjście: P(DOWN/FLAT/UP) jednostki zdarzeń
* Właściciel treningu: master_models
* Środowisko: .venv
* Zależności: grupa korelacji EVENT_DIRECTION
* Odbiorcy: SH:OBSERVATION/OBSERVATION, mm.orchestrator:event_engine, quant.adapters.EventGRU (inferencja SHADOW aktywnego artefaktu)
* Rejestry źródłowe: mm.inventory.MODULES, sh.models.REGISTRY

### `mm:ste_flownet_ret` – STE-FlowNet (adaptacja finansowa) – log-zwrot h zdarzeń
* Pliki: `backend/masterquo/mm/ste_flownet.py`
* Wejście: event splits (Gaussian temporal weighting)
* Wyjście: prognoza log-zwrotu
* Właściciel treningu: master_models
* Środowisko: .venv
* Zależności: grupa korelacji EVENT_DIRECTION
* Odbiorcy: SH:OBSERVATION/OBSERVATION, mm.orchestrator:ste_flownet
* Rejestry źródłowe: mm.inventory.MODULES, sh.models.REGISTRY

### `group:th_direction` – Centrum treningu: kierunek po kosztach (LOGREG/HGB/XGB/RF/SVM + bazowy, aktywne paczki)
* Wyjście: P(DOWN/FLAT/UP) w H świecach po kosztach (kalibracja dev)
* Środowisko: .venv
* Warianty / członkowie: trainhub:TH_BASELINE, trainhub:TH_LOGREG, trainhub:TH_HGB, trainhub:TH_XGB, trainhub:TH_RF, trainhub:TH_SVM
* Rejestry źródłowe: sh.models.REGISTRY

### `kronos:Kronos-small` – Kronos-small (NeoQuasar, przetrenowany, 24,7M) – prognoza świec OHLC
* Pliki: `backend/masterquo/kronos/`, `backend/kronos_runtime/`
* Wyjście: ścieżka OHLC na H świec (cena; pojedyncza próbka – nie prawdopodobieństwo)
* Środowisko: .venv_kronos
* Zależności: grupa korelacji KRONOS_PRICE_PATH
* Odbiorcy: SH:OBSERVATION/OBSERVATION
* Rejestry źródłowe: sh.models.REGISTRY
* Uwagi: pojedyncza ścieżka nie jest prawdopodobieństwem; pretrained ≠ dostrojony do brokera; interwały = dozwolone w ustawieniach Kronos (domyślnie włączone M5, M15)

### `agent:claude` – Agent Claude (weto, opis)
* Wyjście: BUY/SELL/WAIT/NO_TRADE bez prawdopodobieństwa
* Środowisko: .venv
* Zależności: grupa korelacji AGENT
* Odbiorcy: SH:SUPERVISION/SUPERVISION
* Rejestry źródłowe: sh.models.REGISTRY

### `tsfm:chronos2` – Chronos-2 (amazon/chronos-2, 120M, przetrenowany) – kwantyle close
* Pliki: `backend/masterquo/tsfm/`, `backend/tsfm_runtime/`
* Wyjście: kwantyle ceny close na H świec (mediana jako punkt; nieskalibrowane)
* Środowisko: .venv_chronos2
* Zależności: grupa korelacji TSFM_PRICE
* Odbiorcy: SH:OBSERVATION/OBSERVATION
* Rejestry źródłowe: sh.models.REGISTRY
* Uwagi: amazon/chronos-2 (120M); kwantyle modelu, punkt = mediana; nieskalibrowane na danych brokera; interwały = dozwolone w ustawieniach TSFM (domyślnie włączone M5, M15)

### `tsfm:granite_ttm` – Granite TTM (IBM granite-timeseries-ttm-r2, 0,8M, przetrenowany) – prognoza punktowa close
* Pliki: `backend/masterquo/tsfm/`, `backend/tsfm_runtime/`
* Wyjście: prognoza punktowa ceny close na H świec (bez kwantyli; nieskalibrowana)
* Właściciel treningu: tsfm.granite_train
* Środowisko: .venv_granite
* Zależności: grupa korelacji TSFM_PRICE
* Odbiorcy: SH:OBSERVATION/OBSERVATION
* Rejestry źródłowe: sh.models.REGISTRY
* Uwagi: ibm-granite/granite-timeseries-ttm-r2 (TTM R2 512-96, 0,8M); prognoza punktowa (bez kwantyli); nieskalibrowana; 1.40 zamiast FinCast (FinCast: RETIRED, historia zachowana); interwały = dozwolone w ustawieniach TSFM (domyślnie włączone M5, M15)

### `tsfm:tirex2` – TiRex-2 (NX-AI, przetrenowany) – kwantyle close
* Pliki: `backend/masterquo/tsfm/`, `backend/tsfm_runtime/`
* Wyjście: kwantyle ceny close na H świec (mediana jako punkt; nieskalibrowane)
* Środowisko: .venv_tirex2
* Zależności: grupa korelacji TSFM_PRICE
* Odbiorcy: SH:OBSERVATION/OBSERVATION
* Rejestry źródłowe: sh.models.REGISTRY
* Uwagi: rekordy z model_id tsfm:tirex2 (TsfmService, jak Chronos-2 / Granite TTM); kwantyle; nieskalibrowane na danych brokera

### `trainhub:TH_BASELINE` – Bazowy – częstości klas
* Pliki: `backend/masterquo/trainhub/learn.py`, `backend/masterquo/trainhub/inference.py`
* Cechy: trainhub.features.FEATURE_SCHEMA (wspólna implementacja trening/inferencja)
* Właściciel treningu: trainhub.jobs.TrainingCenter
* Właściciel inferencji: trainhub.inference.TrainhubInference
* Środowisko: .venv
* Artefakt: <data>/trainhub/models/<instrument>/<model_key>/<version>
* Rejestry źródłowe: sh.models.REGISTRY (th_direction), trainhub.learn.MODELS
* Uwagi: baseline częstości klas – punkt odniesienia

### `trainhub:TH_LOGREG` – Regresja logistyczna (wieloklasowa)
* Pliki: `backend/masterquo/trainhub/learn.py`, `backend/masterquo/trainhub/inference.py`
* Cechy: trainhub.features.FEATURE_SCHEMA (wspólna implementacja trening/inferencja)
* Właściciel treningu: trainhub.jobs.TrainingCenter
* Właściciel inferencji: trainhub.inference.TrainhubInference
* Środowisko: .venv
* Artefakt: <data>/trainhub/models/<instrument>/<model_key>/<version>
* Rejestry źródłowe: sh.models.REGISTRY (th_direction), trainhub.learn.MODELS

### `trainhub:TH_HGB` – Gradient boosting (histogramowy)
* Pliki: `backend/masterquo/trainhub/learn.py`, `backend/masterquo/trainhub/inference.py`
* Cechy: trainhub.features.FEATURE_SCHEMA (wspólna implementacja trening/inferencja)
* Właściciel treningu: trainhub.jobs.TrainingCenter
* Właściciel inferencji: trainhub.inference.TrainhubInference
* Środowisko: .venv
* Artefakt: <data>/trainhub/models/<instrument>/<model_key>/<version>
* Rejestry źródłowe: sh.models.REGISTRY (th_direction), trainhub.learn.MODELS

### `trainhub:TH_XGB` – XGBoost (CPU)
* Pliki: `backend/masterquo/trainhub/learn.py`, `backend/masterquo/trainhub/inference.py`
* Cechy: trainhub.features.FEATURE_SCHEMA (wspólna implementacja trening/inferencja)
* Właściciel treningu: trainhub.jobs.TrainingCenter
* Właściciel inferencji: trainhub.inference.TrainhubInference
* Środowisko: .venv
* Artefakt: <data>/trainhub/models/<instrument>/<model_key>/<version>
* Rejestry źródłowe: modelhub.families (alias), sh.models.REGISTRY (th_direction), trainhub.learn.MODELS
* Uwagi: alias rodziny family:TH_XGB – jeden artefakt, jeden trening, jeden głos

### `trainhub:TH_RF` – Random Forest
* Pliki: `backend/masterquo/trainhub/learn.py`, `backend/masterquo/trainhub/inference.py`
* Cechy: trainhub.features.FEATURE_SCHEMA (wspólna implementacja trening/inferencja)
* Właściciel treningu: trainhub.jobs.TrainingCenter
* Właściciel inferencji: trainhub.inference.TrainhubInference
* Środowisko: .venv
* Artefakt: <data>/trainhub/models/<instrument>/<model_key>/<version>
* Rejestry źródłowe: modelhub.families (alias), sh.models.REGISTRY (th_direction), trainhub.learn.MODELS
* Uwagi: alias rodziny family:TH_RF – jeden artefakt, jeden trening, jeden głos

### `trainhub:TH_SVM` – SVM (skalowanie + kalibracja chronologiczna)
* Pliki: `backend/masterquo/trainhub/learn.py`, `backend/masterquo/trainhub/inference.py`
* Cechy: trainhub.features.FEATURE_SCHEMA (wspólna implementacja trening/inferencja)
* Właściciel treningu: trainhub.jobs.TrainingCenter
* Właściciel inferencji: trainhub.inference.TrainhubInference
* Środowisko: .venv
* Artefakt: <data>/trainhub/models/<instrument>/<model_key>/<version>
* Rejestry źródłowe: modelhub.families (alias), sh.models.REGISTRY (th_direction), trainhub.learn.MODELS
* Uwagi: alias rodziny family:TH_SVM – jeden artefakt, jeden trening, jeden głos

### `family:TS_ARIMA` – ARIMA (statsmodels) – prognoza log-zwrotu
* Pliki: `backend/masterquo/modelhub/families/arima.py`
* Właściciel treningu: modelhub.families.service (proces obok)
* Właściciel inferencji: modelhub.families.service
* Środowisko: .venv
* Artefakt: <data>/model_families/TS_ARIMA/<instrument>/<run_id>
* Odbiorcy: SH_CONTEXT:expected_move, DECISION:coordinator (REQUIRED / ASSIST – kierunek UP/FLAT/DOWN), PANEL:model_status
* Rejestry źródłowe: modelhub.families.registry

### `family:TS_SARIMAX` – SARIMAX (statsmodels) – zwroty H1 z kalendarzem sesji jako exog
* Pliki: `backend/masterquo/modelhub/families/arima.py`
* Właściciel treningu: modelhub.families.service (proces obok)
* Właściciel inferencji: modelhub.families.service
* Środowisko: .venv
* Artefakt: <data>/model_families/TS_SARIMAX/<instrument>/<run_id>
* Odbiorcy: SH_CONTEXT:expected_move_h1, DECISION:coordinator (REQUIRED / ASSIST – kierunek UP/FLAT/DOWN), PANEL:model_status
* Rejestry źródłowe: modelhub.families.registry

### `family:VOL_GARCH` – GARCH(1,1) (arch) – zmienność warunkowa
* Pliki: `backend/masterquo/modelhub/families/garch.py`
* Właściciel treningu: modelhub.families.service (proces obok)
* Właściciel inferencji: modelhub.families.service
* Środowisko: .venv
* Artefakt: <data>/model_families/VOL_GARCH/<instrument>/<run_id>
* Odbiorcy: SH_CONTEXT:volatility, PANEL:model_status
* Rejestry źródłowe: modelhub.families.registry

### `family:MICROSTRUCTURE` – Mikrostruktura – arkusz brokera (imbalance, OFI, microprice) + klasyfikator reakcji
* Pliki: `backend/masterquo/modelhub/families/micro.py`
* Właściciel treningu: modelhub.families.service (proces obok)
* Właściciel inferencji: modelhub.families.service
* Środowisko: .venv
* Artefakt: <data>/model_families/MICROSTRUCTURE/<instrument>/<run_id>
* Odbiorcy: SH_CONTEXT:entry_quality, PANEL:microstructure
* Rejestry źródłowe: modelhub.families.registry

### `family:PAIR_COINT` – Kointegracja pary + z-score (Engle-Granger)
* Pliki: `backend/masterquo/modelhub/families/pairs.py`
* Właściciel treningu: modelhub.families.service (proces obok)
* Właściciel inferencji: modelhub.families.service
* Środowisko: .venv
* Artefakt: <data>/model_families/PAIR_COINT/<instrument>/<run_id>
* Odbiorcy: PANEL:pair_relation
* Rejestry źródłowe: modelhub.families.registry

### `family:STATARB` – Arbitraż statystyczny – koszyk PCA + reszty (s-score)
* Pliki: `backend/masterquo/modelhub/families/pairs.py`
* Właściciel treningu: modelhub.families.service (proces obok)
* Właściciel inferencji: modelhub.families.service
* Środowisko: .venv
* Artefakt: <data>/model_families/STATARB/<instrument>/<run_id>
* Odbiorcy: PANEL:basket
* Rejestry źródłowe: modelhub.families.registry

### `family:KALMAN_LS` – Filtr Kalmana poziom + nachylenie (rozbudowa mm_kalman)
* Pliki: `backend/masterquo/modelhub/families/kalman_ls.py`
* Właściciel treningu: modelhub.families.service (proces obok)
* Właściciel inferencji: modelhub.families.service
* Środowisko: .venv
* Artefakt: <data>/model_families/KALMAN_LS/<instrument>/<run_id>
* Odbiorcy: SH_CONTEXT:trend_state, PANEL:model_status
* Rejestry źródłowe: modelhub.families.registry

### `family:BREAKOUT` – Breakout – wspólny moduł logiki wybicia (kanał, kompresja, potwierdzenie, retest)
* Pliki: `backend/masterquo/modelhub/families/breakout.py`
* Właściciel treningu: modelhub.families.service (proces obok)
* Właściciel inferencji: modelhub.families.service
* Środowisko: .venv
* Artefakt: <data>/model_families/BREAKOUT/<instrument>/<run_id>
* Odbiorcy: SH_CONTEXT:breakout_state, PANEL:model_status
* Rejestry źródłowe: modelhub.families.registry

### `family:SEQ_LSTM` – LSTM (PyTorch, .venv_deep) – rozkład kierunku po kosztach
* Pliki: `backend/masterquo/modelhub/families/seq.py`
* Właściciel treningu: modelhub.families.service (proces obok)
* Właściciel inferencji: modelhub.families.service
* Środowisko: .venv_deep
* Artefakt: <data>/model_families/SEQ_LSTM/<instrument>/<run_id>
* Odbiorcy: SH_CONTEXT:direction_distribution, MODELHUB:direction_group M5, PANEL:model_status
* Rejestry źródłowe: modelhub.families.registry

### `family:SEQ_GRU` – GRU świecowy (PyTorch, .venv_deep) – rozkład kierunku po kosztach
* Pliki: `backend/masterquo/modelhub/families/seq.py`
* Właściciel treningu: modelhub.families.service (proces obok)
* Właściciel inferencji: modelhub.families.service
* Środowisko: .venv_deep
* Artefakt: <data>/model_families/SEQ_GRU/<instrument>/<run_id>
* Odbiorcy: SH_CONTEXT:direction_distribution, MODELHUB:direction_group M5, PANEL:model_status
* Rejestry źródłowe: modelhub.families.registry

### `family:RL_PPO` – PPO (Stable-Baselines3, Gymnasium replay) – propozycja ekspozycji
* Pliki: `backend/masterquo/modelhub/families/rl.py`
* Właściciel treningu: modelhub.families.service (proces obok)
* Właściciel inferencji: modelhub.families.service
* Środowisko: .venv_deep
* Artefakt: <data>/model_families/RL_PPO/<instrument>/<run_id>
* Odbiorcy: PANEL:model_status
* Rejestry źródłowe: modelhub.families.registry
* Uwagi: akcja RL ≠ p(win)

### `family:NLP_SENTIMENT` – Sentyment tekstu – TF-IDF + regresja logistyczna
* Pliki: `backend/masterquo/modelhub/families/nlp.py`
* Właściciel treningu: modelhub.families.service (proces obok)
* Właściciel inferencji: modelhub.families.service
* Środowisko: .venv
* Artefakt: <data>/model_families/NLP_SENTIMENT/<instrument>/<run_id>
* Odbiorcy: PANEL:news_sentiment
* Rejestry źródłowe: modelhub.families.registry
* Uwagi: sentyment ≠ kierunek XAUUSD bez wyuczonego związku

### `lab:DUMMY` – Lab DUMMY
* Pliki: `backend/masterquo/lab/protocol.py`, `backend/masterquo/lab/service.py`
* Właściciel treningu: lab (training: lab)
* Właściciel inferencji: lab.service
* Środowisko: .venv
* Artefakt: <data>/lab/models/<asset>/
* Rejestry źródłowe: lab.protocol.FAMILIES, sh.models.REGISTRY (lab)
* Uwagi: score innego zdarzenia niż TP setupu – cecha pod własną nazwą

### `lab:RULE` – Lab RULE
* Pliki: `backend/masterquo/lab/protocol.py`, `backend/masterquo/lab/service.py`
* Właściciel treningu: lab (training: lab)
* Właściciel inferencji: lab.service
* Środowisko: .venv
* Artefakt: <data>/lab/models/<asset>/
* Rejestry źródłowe: lab.protocol.FAMILIES, sh.models.REGISTRY (lab)
* Uwagi: score innego zdarzenia niż TP setupu – cecha pod własną nazwą

### `lab:LOGREG` – Lab LOGREG
* Pliki: `backend/masterquo/lab/protocol.py`, `backend/masterquo/lab/service.py`
* Właściciel treningu: lab (training: lab)
* Właściciel inferencji: lab.service
* Środowisko: .venv
* Artefakt: <data>/lab/models/<asset>/
* Rejestry źródłowe: lab.protocol.FAMILIES, sh.models.REGISTRY (lab)
* Uwagi: score innego zdarzenia niż TP setupu – cecha pod własną nazwą

### `lab:TREE` – Lab TREE
* Pliki: `backend/masterquo/lab/protocol.py`, `backend/masterquo/lab/service.py`
* Właściciel treningu: lab (training: lab)
* Właściciel inferencji: lab.service
* Środowisko: .venv
* Artefakt: <data>/lab/models/<asset>/
* Rejestry źródłowe: lab.protocol.FAMILIES, sh.models.REGISTRY (lab)
* Uwagi: score innego zdarzenia niż TP setupu – cecha pod własną nazwą

### `lab:MINIROCKET` – Lab MINIROCKET
* Pliki: `backend/masterquo/lab/protocol.py`, `backend/masterquo/lab/service.py`
* Właściciel treningu: lab (training: lab)
* Właściciel inferencji: lab.service
* Środowisko: .venv
* Artefakt: <data>/lab/models/<asset>/
* Rejestry źródłowe: lab.protocol.FAMILIES, sh.models.REGISTRY (lab)
* Uwagi: score innego zdarzenia niż TP setupu – cecha pod własną nazwą

### `lab:XGB` – Lab XGB
* Pliki: `backend/masterquo/lab/protocol.py`, `backend/masterquo/lab/service.py`
* Właściciel treningu: lab (training: lab)
* Właściciel inferencji: lab.service
* Środowisko: .venv
* Artefakt: <data>/lab/models/<asset>/
* Rejestry źródłowe: lab.protocol.FAMILIES, sh.models.REGISTRY (lab)
* Uwagi: score innego zdarzenia niż TP setupu – cecha pod własną nazwą

### `lab:RESNET1D` – Lab RESNET1D
* Pliki: `backend/masterquo/lab/protocol.py`, `backend/masterquo/lab/service.py`
* Właściciel treningu: lab (training: lab)
* Właściciel inferencji: lab.service
* Środowisko: .venv
* Artefakt: <data>/lab/models/<asset>/
* Rejestry źródłowe: lab.protocol.FAMILIES, sh.models.REGISTRY (lab)
* Uwagi: score innego zdarzenia niż TP setupu – cecha pod własną nazwą

### `lab:SEW_SNN` – Lab SEW_SNN
* Pliki: `backend/masterquo/lab/protocol.py`, `backend/masterquo/lab/service.py`
* Właściciel treningu: lab (training: lab)
* Właściciel inferencji: lab.service
* Środowisko: .venv
* Artefakt: <data>/lab/models/<asset>/
* Rejestry źródłowe: lab.protocol.FAMILIES, sh.models.REGISTRY (lab)
* Uwagi: score innego zdarzenia niż TP setupu – cecha pod własną nazwą

### `lab:LOGREG_PCA` – Eksperyment lab LOGREG_PCA
* Pliki: `backend/masterquo/lab/protocol.py`, `backend/masterquo/lab/service.py`
* Właściciel treningu: lab (training: lab)
* Właściciel inferencji: lab.service
* Środowisko: .venv
* Artefakt: <data>/lab/models/<asset>/
* Rejestry źródłowe: lab.protocol.EXPERIMENTS, sh.models.REGISTRY (lab)
* Uwagi: eksperyment badawczy (PCA / GMM / neutralizacja) – wariant LOGREG, score innego zdarzenia niż TP setupu; artefakt w trybie ALL (training lab-offline, profil PEŁNY TRENING) albo gdy wygra selekcję; t_activate przypina rolę research -> rekord lab:<X> w Quant

### `lab:LOGREG_GMM_AUG` – Eksperyment lab LOGREG_GMM_AUG
* Pliki: `backend/masterquo/lab/protocol.py`, `backend/masterquo/lab/service.py`
* Właściciel treningu: lab (training: lab)
* Właściciel inferencji: lab.service
* Środowisko: .venv
* Artefakt: <data>/lab/models/<asset>/
* Rejestry źródłowe: lab.protocol.EXPERIMENTS, sh.models.REGISTRY (lab)
* Uwagi: eksperyment badawczy (PCA / GMM / neutralizacja) – wariant LOGREG, score innego zdarzenia niż TP setupu; artefakt w trybie ALL (training lab-offline, profil PEŁNY TRENING) albo gdy wygra selekcję; t_activate przypina rolę research -> rekord lab:<X> w Quant

### `lab:LOGREG_NEUTRALIZED` – Eksperyment lab LOGREG_NEUTRALIZED
* Pliki: `backend/masterquo/lab/protocol.py`, `backend/masterquo/lab/service.py`
* Właściciel treningu: lab (training: lab)
* Właściciel inferencji: lab.service
* Środowisko: .venv
* Artefakt: <data>/lab/models/<asset>/
* Rejestry źródłowe: lab.protocol.EXPERIMENTS, sh.models.REGISTRY (lab)
* Uwagi: eksperyment badawczy (PCA / GMM / neutralizacja) – wariant LOGREG, score innego zdarzenia niż TP setupu; artefakt w trybie ALL (training lab-offline, profil PEŁNY TRENING) albo gdy wygra selekcję; t_activate przypina rolę research -> rekord lab:<X> w Quant

### `si:MQ_RESNEXT1D_V2` – Structure Intelligence MQ_RESNEXT1D_V2
* Pliki: `backend/masterquo/lab/structure_nets.py`, `backend/masterquo/lab/si_service.py`
* Właściciel treningu: training (structure_intelligence)
* Właściciel inferencji: lab.si_service
* Środowisko: .venv
* Artefakt: <data>/structure_intelligence/<instrument>/
* Odbiorcy: scalp.dashboard (migawka MTF, prognoza SHADOW), agent.tools get_structure_intelligence, archiwum si_forecasts / si_outcomes
* Rejestry źródłowe: lab.structure_nets.FAMILIES, sh.models.REGISTRY (si_move)

### `si:MQ_SEW_RESNET1D_V2` – Structure Intelligence MQ_SEW_RESNET1D_V2
* Pliki: `backend/masterquo/lab/structure_nets.py`, `backend/masterquo/lab/si_service.py`
* Właściciel treningu: training (structure_intelligence)
* Właściciel inferencji: lab.si_service
* Środowisko: .venv
* Artefakt: <data>/structure_intelligence/<instrument>/
* Odbiorcy: scalp.dashboard (migawka MTF, prognoza SHADOW), agent.tools get_structure_intelligence, archiwum si_forecasts / si_outcomes
* Rejestry źródłowe: lab.structure_nets.FAMILIES, sh.models.REGISTRY (si_move)

### `si:MQ_SEW_RESNEXT_EB_V1` – Structure Intelligence MQ_SEW_RESNEXT_EB_V1
* Pliki: `backend/masterquo/lab/structure_nets.py`, `backend/masterquo/lab/si_service.py`
* Właściciel treningu: training (structure_intelligence)
* Właściciel inferencji: lab.si_service
* Środowisko: .venv
* Artefakt: <data>/structure_intelligence/<instrument>/
* Odbiorcy: scalp.dashboard (migawka MTF, prognoza SHADOW), agent.tools get_structure_intelligence, archiwum si_forecasts / si_outcomes
* Rejestry źródłowe: lab.structure_nets.FAMILIES, sh.models.REGISTRY (si_move)

### `si:MQ_MINIROCKET_RIDGE_V2` – Structure Intelligence MQ_MINIROCKET_RIDGE_V2
* Pliki: `backend/masterquo/lab/si_families.py`, `backend/masterquo/lab/si_service.py`
* Właściciel treningu: training (structure_intelligence)
* Właściciel inferencji: lab.si_service
* Środowisko: .venv
* Artefakt: <data>/structure_intelligence/<instrument>/
* Odbiorcy: scalp.dashboard (migawka MTF, prognoza SHADOW), agent.tools get_structure_intelligence, archiwum si_forecasts / si_outcomes
* Rejestry źródłowe: lab.si_families.FAMILIES, sh.models.REGISTRY (si_move)

### `si:MQ_SPIKE_BRAIN_FINANCE_V1` – Structure Intelligence MQ_SPIKE_BRAIN_FINANCE_V1
* Pliki: `backend/masterquo/lab/si_families.py`, `backend/masterquo/lab/si_service.py`
* Właściciel treningu: training (structure_intelligence)
* Właściciel inferencji: lab.si_service
* Środowisko: .venv
* Artefakt: <data>/structure_intelligence/<instrument>/
* Odbiorcy: scalp.dashboard (migawka MTF, prognoza SHADOW), agent.tools get_structure_intelligence, archiwum si_forecasts / si_outcomes
* Rejestry źródłowe: lab.si_families.FAMILIES, sh.models.REGISTRY (si_move)

### `mm:buzoa` – BUZOA Optimization Engine
* Pliki: `backend/masterquo/mm/buzoa.py`
* Wejście: objective adapter (train/val only)
* Wyjście: OPTIMIZER_RESULT
* Właściciel treningu: NOT_APPLICABLE (optimiser)
* Środowisko: .venv
* Odbiorcy: mm.orchestrator
* Rejestry źródłowe: mm.inventory.MODULES

### `mm:sdom` – SDOm Optimization Engine
* Właściciel treningu: NOT_APPLICABLE
* Środowisko: .venv
* Rejestry źródłowe: mm.inventory.MODULES

### `mm:stfs` – S3CE-Net / STFS (training-time sampling)
* Pliki: `backend/masterquo/mm/stfs.py`
* Wejście: event-encoder feature map [B,T,C]
* Wyjście: training views + losses (no inference output)
* Właściciel treningu: APPLICABLE (as a training strategy)
* Środowisko: .venv
* Odbiorcy: mm.event_engine.train
* Rejestry źródłowe: mm.inventory.MODULES

### `mm:quant_momentum` – Quant Ultimate Momentum Pro / Quant 2nd Model / Momentum AI Fusion
* Właściciel treningu: UNKNOWN
* Środowisko: .venv
* Rejestry źródłowe: mm.inventory.MODULES

### `mm:renko` – Renko Regression Forecasting
* Właściciel treningu: UNKNOWN
* Środowisko: .venv
* Rejestry źródłowe: mm.inventory.MODULES

### `mm:head_shoulders` – Head & Shoulders Structure Detector
* Pliki: `backend/masterquo/analysis/chart_patterns.py (istniejący detektor formacji, w tym H&S)`
* Właściciel treningu: NOT_APPLICABLE
* Środowisko: .venv
* Rejestry źródłowe: mm.inventory.MODULES

### `mm:data_grabber` – Multi-TF Data Grabber Lite
* Pliki: `backend/masterquo/forecast/export.py (istniejący eksport historii zamkniętych świec + metadane + sha256)`
* Właściciel treningu: NOT_APPLICABLE
* Środowisko: .venv
* Rejestry źródłowe: mm.inventory.MODULES

### `mm:tsvp` – Tick Session Volume Profile
* Pliki: `backend/masterquo/mm/tsvp.py`, `mql5/MasterModels/Include/PMW/PMW_TSVPCore.mqh`, `mql5/MasterModels/Indicators/PMW_TickSessionVP.mq5`
* Wejście: MT5 ticks (proxy or actual trade volume)
* Wyjście: buckets, POC, render state
* Właściciel treningu: NOT_APPLICABLE
* Środowisko: .venv
* Odbiorcy: mm.orchestrator:tsvp
* Rejestry źródłowe: mm.inventory.MODULES

### `mm:mathbench` – Math Engine Fidelity Benchmark
* Pliki: `backend/masterquo/mm/mathbench.py`, `mql5/MathFidelity/train_export_model.py`, `mql5/MathFidelity/Experts/MathFidelityBenchmark_EA.mq5`, `mql5/MathFidelity/Indicators/FidelityMonitor.mq5`, `mql5/MathFidelity/Scripts/MathFidelity_SelfTest.mq5`
* Wyjście: BENCHMARK_RESULT
* Właściciel treningu: NOT_APPLICABLE
* Środowisko: .venv
* Odbiorcy: mm.orchestrator:mathbench
* Rejestry źródłowe: mm.inventory.MODULES

### `mm:chart_sync` – MT5 Multi-Timeframe Chart Synchronization
* Pliki: `frontend (istniejąca opcjonalna synchronizacja wykresów w panelu, J1)`
* Właściciel treningu: NOT_APPLICABLE
* Środowisko: .venv
* Rejestry źródłowe: mm.inventory.MODULES

### `mm:fusion_board` – Evidence board (cross-model integration layer, discovered need)
* Pliki: `backend/masterquo/mm/fusion.py`
* Właściciel treningu: NOT_APPLICABLE
* Środowisko: .venv
* Odbiorcy: mm.service, API /api/v1/mm/live (board)
* Rejestry źródłowe: mm.inventory.MODULES

### `analysis:montecarlo` – Monte Carlo (PMW-MC-1) – symulacja ścieżek
* Pliki: `backend/masterquo/montecarlo/`
* Środowisko: .venv
* Rejestry źródłowe: runtime.py
* Uwagi: MODEL_SIMULATED – wynik symulacji, nie prawdopodobieństwo skalibrowane na zdarzeniach

### `analysis:zones` – Mapa stref (PMW-ZONES)
* Pliki: `backend/masterquo/zones/`
* Środowisko: .venv
* Odbiorcy: evaluation.service (zone_context kandydata), migawka Quant (rekord STATE)
* Rejestry źródłowe: runtime.py
* Uwagi: rekord STATE (ZONE_MAP_SUMMARY) w migawce Quant bez cech MetaModelu – quant/features.py nie mapuje stref; cechy zone_* trafiają do kandydata i ledgera oceny (evaluation.zone_context)

### `analysis:market_zones` – Strefy rynkowe M1/M5/M15/M30 (1.28)
* Pliki: `backend/masterquo/zones/market_service.py`
* Środowisko: .venv
* Rejestry źródłowe: runtime.py

### `analysis:indicators` – Wskaźniki PMW-IND-1 (AVWAP sesja/zdarzenie/manualny, semiwariancja, percentyl spreadu, cechy profilu sesji, mikrostruktura arkusza/OFI, relacja DXY)
* Pliki: `backend/masterquo/indicators/`
* Środowisko: .venv
* Rejestry źródłowe: runtime.py

### `analysis:svp` – Session Volume Profile (PMW-SVP-1)
* Pliki: `backend/masterquo/svp/`, `backend/masterquo/sh/pack/features.py`
* Środowisko: .venv
* Odbiorcy: SH pack PMW_HG08 / PMW_SC10 (sh/pack/detectors.value_area_rejection – profil poprzedniej sesji), panel SVP (profile użytkownika)
* Rejestry źródłowe: runtime.py

### `analysis:dxy_correlation` – Korelacja XAUUSD–DXY (PMW-IND-1 dxy)
* Pliki: `backend/masterquo/indicators/`
* Środowisko: .venv
* Rejestry źródłowe: runtime.py

### `analysis:walls` – Walls D1 (σ: import IV → IV ręczna → HV_PROXY domyślnie)
* Pliki: `backend/masterquo/analysis/walls.py`, `backend/masterquo/analysis/iv_import.py`
* Środowisko: .venv
* Odbiorcy: strategies.s12_walls_range (ścieżka A, S12), panel / API ścian zmienności
* Rejestry źródłowe: runtime.py

### `analysis:evaluation` – AI Setup Probability Engine (PMW-EVAL)
* Pliki: `backend/masterquo/evaluation/`
* Środowisko: .venv
* Rejestry źródłowe: runtime.py

### `quant:metamodel` – PMW Quant MetaModel (logistyczny + net R ridge, OOF, kalibracja)
* Pliki: `backend/masterquo/quant/metamodel.py`
* Środowisko: .venv
* Rejestry źródłowe: runtime.py

### `ext:catboost` – CatBoost
* Środowisko: .venv
* Rejestry źródłowe: lab/traceability.py (wzmianka)

### `quant:tabicl_v2` – TabICLv2 (estymator confidence kandydata, in-context)
* Pliki: `backend/masterquo/quant/tabicl.py`, `backend/tabicl_runtime/`
* Środowisko: .venv_tabicl
* Rejestry źródłowe: quant.ids.EXTRA_PRODUCERS (1.46)

### `flow:markov3` – Markov3 / Markov-diff flow (MQ_MARKOV3_FLOW_V1)
* Pliki: `backend/masterquo/lab/flow_context/markov.py`
* Środowisko: .venv
* Rejestry źródłowe: quant.ids.EXTRA_PRODUCERS (1.46)

### `si:LOGREG` – Structure Intelligence LOGREG (FAMILIES_ALL)
* Pliki: `backend/masterquo/lab/structure_task.py`
* Środowisko: .venv
* Rejestry źródłowe: quant.ids.EXTRA_PRODUCERS (1.46)

### `si:XGB` – Structure Intelligence XGB (FAMILIES_ALL)
* Pliki: `backend/masterquo/lab/structure_task.py`
* Środowisko: .venv
* Rejestry źródłowe: quant.ids.EXTRA_PRODUCERS (1.46)

### `quotes:MQ_NEWTONIAN_QUOTES_V2` – QuoteEngine (kinematyka notowań)
* Pliki: `backend/masterquo/lab/quotes.py`
* Środowisko: .venv
* Rejestry źródłowe: quant.ids.EXTRA_PRODUCERS (1.46)

### `lab:M29_fourier` – Lab M29 Fourier (prognoza archiwizowana)
* Pliki: `backend/masterquo/lab/service.py`
* Środowisko: .venv
* Rejestry źródłowe: quant.ids.EXTRA_PRODUCERS (1.46)

### `lab:M31_tick_kinematics` – Lab M31 kinematyka ticków (legacy obok QuoteEngine)
* Pliki: `backend/masterquo/lab/service.py`
* Środowisko: .venv
* Rejestry źródłowe: quant.ids.EXTRA_PRODUCERS (1.46)

### `lab:M42_trade_pad` – Lab M42 trade pad (kalkulator)
* Pliki: `backend/masterquo/api/app.py`
* Środowisko: .venv
* Rejestry źródłowe: quant.ids.EXTRA_PRODUCERS (1.46)

### `lab:M39_M41_edge` – Lab M39–M41 RepaintInspector / edge drift / bootstrap
* Pliki: `backend/masterquo/lab/service.py`
* Środowisko: .venv
* Rejestry źródłowe: quant.ids.EXTRA_PRODUCERS (1.46)

### `research:graph50` – Research Graph50 (SCORE per cel)
* Pliki: `backend/masterquo/research/`
* Środowisko: .venv
* Rejestry źródłowe: quant.ids.EXTRA_PRODUCERS (1.46)
* Uwagi: rekordy z jawnym canonical_id research:graph50:<cel>

### `research:g7_smc_radar` – Research G7 SMC radar
* Pliki: `backend/masterquo/research/`
* Środowisko: .venv
* Rejestry źródłowe: quant.ids.EXTRA_PRODUCERS (1.46)

### `research:sdformerflow` – Research SDformerFlow (TH_SDFORMERFLOW)
* Pliki: `backend/masterquo/research/`
* Środowisko: .venv_tirex2 (torch)
* Rejestry źródłowe: quant.ids.EXTRA_PRODUCERS (1.46)
* Uwagi: wymaga środowiska z torch 2.14.1

### `mm:kalman_params` – Parametry Kalmana (kalibracja BUZOA)
* Pliki: `backend/masterquo/mm/orchestrator.py`
* Środowisko: .venv
* Rejestry źródłowe: quant.ids.EXTRA_PRODUCERS (1.46)

### `mm:robust_vol` – Robust volatility (część breakout_zones)
* Pliki: `backend/masterquo/mm/`
* Środowisko: .venv
* Rejestry źródłowe: quant.ids.EXTRA_PRODUCERS (1.46)

### `mm:drift` – Drift (PMW-MM)
* Pliki: `backend/masterquo/mm/drift.py`
* Środowisko: .venv
* Rejestry źródłowe: quant.ids.EXTRA_PRODUCERS (1.46)

### `mm:bat_encoder` – BAT encoder (losowe wagi, SHADOW_UNTRAINED)
* Pliki: `backend/masterquo/mm/`, `backend/masterquo/api/wf32_routes.py`
* Środowisko: .venv
* Rejestry źródłowe: quant.ids.EXTRA_PRODUCERS (1.46)

### `extind:sar_context` – Kontekst SAR (kalibracja siatki)
* Pliki: `backend/masterquo/extind/`
* Środowisko: .venv
* Rejestry źródłowe: quant.ids.EXTRA_PRODUCERS (1.46)

### `extind:knowledge` – Reguły wiedzy IND-K01..K12
* Pliki: `backend/masterquo/extind/knowledge.py`
* Środowisko: .venv
* Rejestry źródłowe: quant.ids.EXTRA_PRODUCERS (1.46)

### `extind:IQ_GOLD_GANN` – IQ Gold Gann (wskaźnik MT5, eksport kopert)
* Pliki: `mql5/PMW_ExtIndicatorExporter.mq5`
* Środowisko: MQL5 (MT5)
* Rejestry źródłowe: quant.ids.EXTRA_PRODUCERS (1.46)

### `extind:IQ_STAR_LINES` – IQ Star Lines (wskaźnik MT5, eksport kopert)
* Pliki: `mql5/PMW_ExtIndicatorExporter.mq5`
* Środowisko: MQL5 (MT5)
* Rejestry źródłowe: quant.ids.EXTRA_PRODUCERS (1.46)

### `extind:PAL02M` – PAL02M (tożsamość nieustalona)
* Pliki: `config/extind_manifests_v1.json`
* Środowisko: -
* Rejestry źródłowe: quant.ids.EXTRA_PRODUCERS (1.46)

### `strategies:regime` – MarketRegimeEngine MQ-REGIME-1.0.0 (wybór strategii ACTIVE)
* Pliki: `backend/masterquo/strategies/regime.py`
* Środowisko: .venv
* Rejestry źródłowe: quant.ids.EXTRA_PRODUCERS (1.46)

### `analysis:signals` – Poziomy / range M5 / MITP / neutralizacja
* Pliki: `backend/masterquo/analysis/`
* Środowisko: .venv
* Rejestry źródłowe: quant.ids.EXTRA_PRODUCERS (1.46)

### `analytics:session_engine` – Silnik sesji (boxy sesyjne)
* Pliki: `backend/masterquo/analytics/`
* Środowisko: .venv
* Rejestry źródłowe: quant.ids.EXTRA_PRODUCERS (1.46)

### `engine:volzones` – Strefy zmienności (panel)
* Pliki: `backend/masterquo/engine/service.py`
* Środowisko: .venv
* Rejestry źródłowe: quant.ids.EXTRA_PRODUCERS (1.46)

### `apollo:market_trap` – Market trap (SHADOW, ostrzeżenia)
* Pliki: `backend/masterquo/apollo/`
* Środowisko: .venv
* Rejestry źródłowe: quant.ids.EXTRA_PRODUCERS (1.46)

### `baskets:sfb` – Strategy Filter Bucket koszyków FX
* Pliki: `backend/masterquo/baskets/sfb.py`
* Środowisko: .venv
* Rejestry źródłowe: quant.ids.EXTRA_PRODUCERS (1.46)

### `ml:decision_tree_ranker` – Decision tree ranker (WF3.2)
* Pliki: `backend/masterquo/api/wf32_routes.py`
* Środowisko: .venv
* Rejestry źródłowe: quant.ids.EXTRA_PRODUCERS (1.46)

### `ml:association_rules` – Reguły asocjacyjne (WF3.2)
* Pliki: `backend/masterquo/api/wf32_routes.py`
* Środowisko: .venv
* Rejestry źródłowe: quant.ids.EXTRA_PRODUCERS (1.46)

### `ml:pt_directional_skill` – Test Pesarana–Timmermanna (WF3.2)
* Pliki: `backend/masterquo/api/wf32_routes.py`
* Środowisko: .venv
* Rejestry źródłowe: quant.ids.EXTRA_PRODUCERS (1.46)

### `ml:change_point_engine` – Change points PELT (WF3.2)
* Pliki: `backend/masterquo/api/wf32_routes.py`
* Środowisko: .venv
* Rejestry źródłowe: quant.ids.EXTRA_PRODUCERS (1.46)

### `forecast:long_horizon` – Rozkład 24–72 h (WF3.2)
* Pliki: `backend/masterquo/api/wf32_routes.py`
* Środowisko: .venv
* Rejestry źródłowe: quant.ids.EXTRA_PRODUCERS (1.46)

### `forecast:double_retest_v2` – Double Retest v2 (flagi świec prognozy)
* Pliki: `backend/masterquo/forecast/`
* Środowisko: .venv_candles
* Rejestry źródłowe: quant.ids.EXTRA_PRODUCERS (1.46)

### `scalp:C_policy` – Scalp C – ocena polityki hedge vs REDUCE w replay
* Pliki: `backend/masterquo/training/runner.py`
* Środowisko: .venv_candles
* Rejestry źródłowe: quant.ids.EXTRA_PRODUCERS (1.46)

