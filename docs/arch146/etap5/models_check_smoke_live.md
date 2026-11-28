# models check – 2026-11-28T11:43:39Z

Instrument XAUUSD; warstwy: rejestr + środowisko + import + smoke + na żywo (60.0 s, Runtime demo). Dane: SYNTHETIC_TEST (technicznie, nie jakość).

| kanoniczne id | kategoria | środowisko | env | import | trening | artefakt | predykcja | kontrakt | na żywo | stan rejestru | status | uzasadnienie |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `agent:claude` | AGENT | .venv | – | – | – | – | NIEZWERYFIKOWANY | OK | SKIP | SHADOW_ONLY | **NIEZWERYFIKOWANY** | predict: brak klucza Anthropic – wywołanie API niesprawdzone \| sprawdzone tutaj: contract |
| `extind:IQ_GOLD_GANN` | NATIVE_MQL5 | MQL5 (MT5) | NIEZWERYFIKOWANY | – | – | – | NIEZWERYFIKOWANY | OK | SKIP | NOT_EVALUATED | **NIEZWERYFIKOWANY** | env: natywny wskaźnik MQL5 Market (produkt 134935) działa tylko w terminalu MT5 (Windows) z licencją; eksporter mql5/PMW_ExtIndicatorExporter.mq5 nieuruchomiony – sprawdzono wyłącznie stronę bota (koperta pmw-extind-1);  |
| `extind:IQ_STAR_LINES` | NATIVE_MQL5 | MQL5 (MT5) | NIEZWERYFIKOWANY | – | – | – | NIEZWERYFIKOWANY | OK | SKIP | NOT_EVALUATED | **NIEZWERYFIKOWANY** | env: natywny wskaźnik MQL5 Market (produkt 145140) działa tylko w terminalu MT5 (Windows) z licencją; eksporter mql5/PMW_ExtIndicatorExporter.mq5 nieuruchomiony – sprawdzono wyłącznie stronę bota (koperta pmw-extind-1);  |
| `analysis:dxy_correlation` | ANALYSIS | .venv | – | OK | – | – | OK | OK | OK | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `analysis:evaluation` | ANALYSIS | .venv | – | OK | – | – | OK | OK | SKIP | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `analysis:indicators` | ANALYSIS | .venv | – | OK | – | – | OK | OK | OK | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `analysis:market_zones` | ANALYSIS | .venv | – | OK | – | – | OK | – | SKIP | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `analysis:montecarlo` | SIMULATION | .venv | – | OK | OK | OK | OK | OK | OK | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `analysis:signals` | RULE_OR_MEASUREMENT | .venv | – | OK | – | – | OK | – | SKIP | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `analysis:svp` | ANALYSIS | .venv | – | OK | – | – | OK | – | SKIP | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `analysis:walls` | ANALYSIS | .venv | – | OK | – | – | OK | – | SKIP | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `analysis:zones` | ANALYSIS | .venv | – | OK | – | – | OK | OK | OK | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `analytics:session_engine` | RULE_OR_MEASUREMENT | .venv | – | OK | – | – | OK | – | SKIP | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `apollo:market_trap` | RULE_OR_MEASUREMENT | .venv | – | OK | – | – | OK | – | SKIP | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `baskets:sfb` | RULE_OR_MEASUREMENT | .venv | – | OK | – | – | OK | – | SKIP | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `context_ind:context_move_m5` | MODEL_TRAINED | .venv | – | OK | OK | OK | OK | OK | SKIP | NOT_CONNECTED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `engine:volzones` | RULE_OR_MEASUREMENT | .venv | – | OK | – | – | OK | – | SKIP | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `extind:indicator_context` | MODEL_TRAINED | .venv | – | OK | OK | OK | OK | OK | SKIP | NOT_TRAINED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `extind:knowledge` | RULE_OR_MEASUREMENT | .venv | – | OK | – | – | OK | OK | SKIP | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `extind:sar_context` | RULE_OR_MEASUREMENT | .venv | – | OK | OK | – | OK | OK | SKIP | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `family:BREAKOUT` | MODEL_ESTIMATED | .venv | – | OK | OK | OK | OK | OK | OK | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `family:KALMAN_LS` | MODEL_ESTIMATED | .venv | – | OK | OK | OK | OK | OK | OK | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `family:MICROSTRUCTURE` | MEASUREMENT | .venv | – | OK | OK | OK | OK | OK | OK | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `family:NLP_SENTIMENT` | MODEL_TRAINED | .venv | – | OK | OK | OK | OK | OK | OK | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `family:PAIR_COINT` | MODEL_TRAINED | .venv | – | OK | OK | OK | OK | OK | OK | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `family:RL_PPO` | MODEL_TRAINED | .venv_deep | OK | OK | OK | OK | OK | OK | OK | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `family:SEQ_GRU` | MODEL_TRAINED | .venv_deep | OK | OK | OK | OK | OK | OK | OK | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `family:SEQ_LSTM` | MODEL_TRAINED | .venv_deep | OK | OK | OK | OK | OK | OK | OK | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `family:STATARB` | MODEL_TRAINED | .venv | – | OK | OK | OK | OK | OK | OK | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `family:TS_ARIMA` | MODEL_TRAINED | .venv | – | OK | OK | OK | OK | OK | OK | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `family:TS_SARIMAX` | MODEL_TRAINED | .venv | – | OK | OK | OK | OK | OK | OK | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `family:VOL_GARCH` | MODEL_TRAINED | .venv | – | OK | OK | OK | OK | OK | OK | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `flow:markov3` | MODEL_TRAINED | .venv | – | OK | OK | OK | OK | OK | SKIP | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `flow:reaction_m1` | MODEL_TRAINED | .venv | – | OK | OK | OK | OK | OK | SKIP | NOT_TRAINED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `forecast:double_retest_v2` | RULE_OR_MEASUREMENT | .venv_candles | OK | OK | – | – | OK | OK | SKIP | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `forecast:gold_candles` | MODEL_TRAINED | .venv_candles | OK | OK | OK | OK | OK | OK | OK | NOT_TRAINED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `forecast:long_horizon` | RULE_OR_MEASUREMENT | .venv | – | OK | – | – | OK | OK | SKIP | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `kronos:Kronos-small` | MODEL_PRETRAINED | .venv_kronos | OK | OK | – | OK | OK | OK | OK | UNAVAILABLE | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `lab:DUMMY` | BASELINE | .venv | – | OK | OK | OK | OK | OK | OK | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `lab:LOGREG` | MODEL_TRAINED | .venv | – | OK | OK | OK | OK | OK | OK | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `lab:LOGREG_GMM_AUG` | RESEARCH | .venv | – | OK | OK | OK | OK | OK | OK | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `lab:LOGREG_NEUTRALIZED` | RESEARCH | .venv | – | OK | OK | OK | OK | OK | OK | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `lab:LOGREG_PCA` | RESEARCH | .venv | – | OK | OK | OK | OK | OK | OK | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `lab:M29_fourier` | RULE_OR_MEASUREMENT | .venv | – | OK | – | OK | OK | OK | SKIP | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `lab:M31_tick_kinematics` | RULE_OR_MEASUREMENT | .venv | – | OK | – | – | OK | OK | SKIP | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `lab:M39_M41_edge` | TOOL | .venv | – | OK | – | – | OK | OK | SKIP | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `lab:M42_trade_pad` | TOOL | .venv | – | OK | – | – | OK | OK | SKIP | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `lab:MINIROCKET` | MODEL_TRAINED | .venv | – | OK | OK | OK | OK | OK | OK | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `lab:RESNET1D` | MODEL_TRAINED | .venv | – | OK | OK | OK | OK | OK | OK | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `lab:RULE` | BASELINE | .venv | – | OK | OK | OK | OK | OK | OK | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `lab:SEW_SNN` | MODEL_TRAINED | .venv | – | OK | OK | OK | OK | OK | OK | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `lab:TREE` | MODEL_TRAINED | .venv | – | OK | OK | OK | OK | OK | OK | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `lab:XGB` | MODEL_TRAINED | .venv | – | OK | OK | OK | OK | OK | OK | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `ml:association_rules` | RULE_OR_MEASUREMENT | .venv | – | OK | – | – | OK | OK | SKIP | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `ml:change_point_engine` | RULE_OR_MEASUREMENT | .venv | – | OK | – | – | OK | OK | SKIP | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `ml:decision_tree_ranker` | MODEL_TRAINED | .venv | – | OK | OK | – | OK | OK | SKIP | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `ml:legacy_s01_s12` | MODEL_TRAINED | .venv | – | OK | OK | OK | OK | OK | SKIP | UNAVAILABLE | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `ml:pt_directional_skill` | TOOL | .venv | – | OK | – | – | OK | OK | SKIP | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `ml_scalp:xgb_net_r` | MODEL_TRAINED | .venv | – | OK | OK | OK | OK | OK | SKIP | NOT_TRAINED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `mm:align_mean` | RULE_OR_MEASUREMENT | .venv | – | OK | – | – | OK | OK | OK | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `mm:bat_encoder` | RESEARCH | .venv | – | OK | – | – | OK | OK | SKIP | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `mm:breakout_zones` | RULE_OR_MEASUREMENT | .venv | – | OK | – | – | OK | OK | OK | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `mm:buzoa` | OPTIMIZER | .venv | – | OK | – | – | OK | OK | SKIP | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `mm:drift` | RULE_OR_MEASUREMENT | .venv | – | OK | – | – | OK | OK | SKIP | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `mm:event_engine_dir3` | MODEL_TRAINED | .venv | – | OK | OK | OK | OK | OK | OK | NOT_TRAINED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `mm:fusion_board` | DATA_INFRA | .venv | – | OK | – | – | OK | OK | SKIP | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `mm:gpr_logret` | MODEL_TRAINED | .venv | – | OK | OK | OK | OK | OK | OK | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `mm:hdc_dir3` | MODEL_TRAINED | .venv | – | OK | OK | OK | SKIP | – | SKIP | NOT_TRAINED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość); pominięte: predict: brak ścieżki predykcji na żywo (stan faktyczny): artefakt wczytywalny (hdc.from_state), ale bez konsumenta, quant/inventory.py:87 |
| `mm:kalman_cross` | RULE_OR_MEASUREMENT | .venv | – | OK | – | – | OK | OK | OK | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `mm:kalman_params` | TRAINABLE | .venv | – | OK | OK | OK | – | – | SKIP | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `mm:mathbench` | BENCHMARK | .venv | – | OK | OK | OK | OK | – | SKIP | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `mm:multi_indicator` | RULE_OR_MEASUREMENT | .venv | – | OK | – | – | OK | OK | OK | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `mm:robust_vol` | RULE_OR_MEASUREMENT | .venv | – | OK | – | – | OK | OK | SKIP | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `mm:smc_fvg` | RULE_OR_MEASUREMENT | .venv | – | OK | – | – | OK | OK | OK | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `mm:ste_flownet_ret` | MODEL_TRAINED | .venv | – | OK | OK | OK | SKIP | – | SKIP | NOT_TRAINED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość); pominięte: predict: brak ścieżki predykcji na żywo (stan faktyczny): quant/inventory.py:91 adapter=None ('tylko artefakt badawczy'), brak loadera w k |
| `mm:stfs` | TRAINABLE | .venv | – | OK | OK | – | – | – | SKIP | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `mm:tsvp` | VISUALIZATION | .venv | – | OK | – | – | OK | OK | SKIP | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `nss:tcn` | MODEL_TRAINED | .venv | – | OK | OK | OK | OK | OK | SKIP | NOT_TRAINED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `quant:metamodel` | META_MODEL | .venv | – | OK | OK | OK | OK | OK | SKIP | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `quant:tabicl_v2` | MODEL_PRETRAINED | .venv_tabicl | OK | OK | – | OK | OK | OK | SKIP | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `quotes:MQ_NEWTONIAN_QUOTES_V2` | RULE_OR_MEASUREMENT | .venv | – | OK | – | – | OK | OK | SKIP | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `research:g7_smc_radar` | RESEARCH | .venv | – | OK | – | – | OK | OK | OK | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `research:graph50` | RESEARCH | .venv | – | OK | OK | OK | OK | OK | OK | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `research:sdformerflow` | RESEARCH | .venv_tirex2 (torch) | OK | OK | OK | OK | OK | OK | SKIP | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `rule:atr_vol` | RULE_OR_MEASUREMENT | .venv | – | – | – | – | OK | OK | OK | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `rule:candles_patterns` | RULE_OR_MEASUREMENT | .venv | – | – | – | – | OK | – | SKIP | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `rule:data_quality` | RULE_OR_MEASUREMENT | .venv | – | OK | – | – | OK | OK | OK | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `rule:decomposition` | RULE_OR_MEASUREMENT | .venv | – | – | – | – | OK | – | SKIP | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `rule:flow_sr` | RULE_OR_MEASUREMENT | .venv | – | – | – | – | OK | – | SKIP | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `rule:fractal` | RULE_OR_MEASUREMENT | .venv | – | – | – | – | OK | – | SKIP | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `rule:liquidity` | RULE_OR_MEASUREMENT | .venv | – | – | – | – | OK | – | SKIP | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `rule:news` | RULE_OR_MEASUREMENT | .venv | – | OK | – | – | OK | OK | OK | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `rule:regime_v2` | RULE_OR_MEASUREMENT | .venv | – | – | – | – | OK | OK | OK | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `rule:risk_engine` | RULE_OR_MEASUREMENT | .venv | – | OK | – | – | OK | – | SKIP | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `rule:smc_pullback` | RULE_OR_MEASUREMENT | .venv | – | – | – | – | OK | – | SKIP | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `rule:structure_v2` | RULE_OR_MEASUREMENT | .venv | – | – | – | – | OK | OK | OK | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `rule:vamd` | RULE_OR_MEASUREMENT | .venv | – | – | – | – | OK | – | SKIP | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `scalp:A_direction` | MODEL_TRAINED | .venv_candles | OK | OK | OK | OK | OK | OK | OK | NOT_TRAINED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `scalp:B_setup_quality` | MODEL_TRAINED | .venv_candles | OK | – | OK | OK | OK | OK | SKIP | NOT_TRAINED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `scalp:C_policy` | TOOL | .venv_candles | OK | OK | – | – | OK | OK | SKIP | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `sh:tp_model` | MODEL_TRAINED | .venv | – | OK | OK | OK | OK | OK | SKIP | NOT_TRAINED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `si:LOGREG` | MODEL_TRAINED | .venv | – | OK | OK | OK | OK | OK | SKIP | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `si:MQ_MINIROCKET_RIDGE_V2` | MODEL_TRAINED | .venv | – | OK | OK | OK | OK | OK | SKIP | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `si:MQ_RESNEXT1D_V2` | MODEL_TRAINED | .venv | – | OK | OK | OK | OK | OK | SKIP | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `si:MQ_SEW_RESNET1D_V2` | MODEL_TRAINED | .venv | – | OK | OK | OK | OK | OK | SKIP | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `si:MQ_SEW_RESNEXT_EB_V1` | MODEL_TRAINED | .venv | – | OK | OK | OK | OK | OK | SKIP | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `si:MQ_SPIKE_BRAIN_FINANCE_V1` | MODEL_TRAINED | .venv | – | OK | OK | OK | OK | OK | SKIP | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `si:XGB` | MODEL_TRAINED | .venv | – | OK | OK | OK | OK | OK | SKIP | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `strategies:regime` | RULE_OR_MEASUREMENT | .venv | – | OK | – | – | OK | – | SKIP | NOT_EVALUATED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `trainhub:TH_BASELINE` | MODEL_TRAINED | .venv | – | OK | OK | OK | OK | OK | OK | NOT_TRAINED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `trainhub:TH_HGB` | MODEL_TRAINED | .venv | – | OK | OK | OK | OK | OK | OK | NOT_TRAINED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `trainhub:TH_LOGREG` | MODEL_TRAINED | .venv | – | OK | OK | OK | OK | OK | OK | NOT_TRAINED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `trainhub:TH_RF` | MODEL_TRAINED | .venv | – | OK | OK | OK | OK | OK | OK | NOT_TRAINED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `trainhub:TH_SVM` | MODEL_TRAINED | .venv | – | OK | OK | OK | OK | OK | OK | NOT_TRAINED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `trainhub:TH_XGB` | MODEL_TRAINED | .venv | – | OK | OK | OK | OK | OK | OK | NOT_TRAINED | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `tsfm:chronos2` | MODEL_PRETRAINED | .venv_chronos2 | OK | OK | – | OK | OK | OK | OK | UNAVAILABLE | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `tsfm:granite_ttm` | MODEL_PRETRAINED | .venv_granite | OK | OK | – | OK | OK | OK | OK | UNAVAILABLE | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `tsfm:tirex2` | MODEL_PRETRAINED | .venv_tirex2 | OK | OK | – | OK | OK | OK | OK | UNAVAILABLE | **DZIAŁA** | ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość) |
| `extind:PAL02M` | NO_SPEC | - | – | – | – | – | – | – | SKIP | UNAVAILABLE | **NO_SPEC** | NO_SPEC |
| `mm:chart_sync` | NO_SPEC | .venv | – | – | – | – | – | – | SKIP | UNAVAILABLE | **NO_SPEC** | NO_SPEC |
| `mm:data_grabber` | NO_SPEC | .venv | – | – | – | – | – | – | SKIP | UNAVAILABLE | **NO_SPEC** | NO_SPEC |
| `mm:head_shoulders` | NO_SPEC | .venv | – | – | – | – | – | – | SKIP | UNAVAILABLE | **NO_SPEC** | NO_SPEC |
| `mm:quant_momentum` | NO_SPEC | .venv | – | – | – | – | – | – | SKIP | UNAVAILABLE | **NO_SPEC** | NO_SPEC |
| `mm:renko` | NO_SPEC | .venv | – | – | – | – | – | – | SKIP | UNAVAILABLE | **NO_SPEC** | NO_SPEC |
| `mm:sdom` | NO_SPEC | .venv | – | – | – | – | – | – | SKIP | UNAVAILABLE | **NO_SPEC** | NO_SPEC |
| `ext:catboost` | NOT_IMPLEMENTED | .venv | – | – | – | – | – | – | SKIP | UNAVAILABLE | **NOT_IMPLEMENTED** | wspomniany w dokumentacji / traceability (M06); brak implementacji i zależności w kodzie |

Podsumowanie: NIEZWERYFIKOWANY 3, DZIAŁA 115, NO_SPEC 7, NOT_IMPLEMENTED 1

