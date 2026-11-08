# Raport testów – PMW Quant Core (1.35.0)

Środowisko: kontener Linux, Python 3.13, Chromium (Playwright), symulator terminala MT5 (`--demo`, dane SYNTHETIC). Data: 8 listopada 2026 r.
Brak Windows, WebView2, prawdziwego MT5 i danych użytkownika. Wszystko, co ich wymaga, ma status **NOT_RUN** poniżej.

## Podsumowanie

| Zestaw | Wynik |
|---|---|
| `test_quant_core` (31 testów – tabela specyfikacji) | **PASS** |
| `test_ui_quant` (4 testy – API, strony, CLI na żywym bocie) | **PASS** |
| Regresja nie-UI: 93 moduły, 1140 testów (przed poprawkami) | 91 PASS, 2 FAIL → poprawione → `test_time_and_data`, `test_zones` + `test_quant_core`, `test_evaluation`: **PASS** (115 testów po poprawce) |
| Regresja UI: 20 modułów, 117 testów | **PASS** |
| `test_kronos_runtime` w środowisku Kronos (PyTorch) | **PASS** 7, **SKIPPED** 1 (oficjalne wagi – brak `MQ_KRONOS_WEIGHTS_DIR`) |
| `frontend`: `npm run typecheck`, `npm run build` | **PASS** |
| `tools/check_requirements_win.py` (w `build_release.py`): 4 pliki × Python 3.13 / 3.12 | **PASS** |
| `tools/verify_release.py --all` (obie paczki 1.35.0) | **PASS** |
| Start z paczki DESKTOP i folderu 1.35.0: ścieżka ze spacjami i polskimi znakami, konfiguracja v12→v13, migracje, koordynator, rodziny, Studio, **Quant SHADOW z kompletnym cyklem**, **CLI quant z paczki**, restart (tryb SHADOW bez zmian) | **PASS** 17/17 każda |

Pominięcia w regresji (SKIPPED, nie PASS):

| Moduł | Pominięte testy | Przyczyna |
|---|---|---|
| `test_kronos_runtime` | 8 w `.venv` | brak PyTorch; uruchomione osobno w środowisku Kronos (wyżej) |
| `test_mm_integration` | 2 | brak OpenCL / ONNX |
| `test_train_all` | 2 | brak `.venv_candles` |

Dwie porażki z pierwszej regresji powstały przez zmiany 1.35 i zostały naprawione:
1. `test_time_and_data`: reguła projektu „instrument zawsze jawnie” – CLI `quant` miał domyślne `XAUUSD`. Teraz `--instrument` jest wymagany w train / list / activate / rollback / mode.
2. `test_zones`: test zakładał ACCEPT z przedziałem Wilsona z liczności kalibracji, a to zostało celowo usunięte (PMW-EVAL-ENGINE-2). Test podaje teraz zwalidowany przedział.

## Mapa tabeli akceptacyjnej specyfikacji (§16) na testy

| Wymaganie | Test | Wynik |
|---|---|---|
| Zmiana danych po chwili t nie zmienia historii w t | `TestSnapshotPointInTime.test_change_after_t_does_not_change_history_at_t` | PASS |
| Otwarta świeca M15/H1 nie trafia do snapshotu | `TestSnapshotPointInTime.test_forming_bar_and_future_availability_excluded` | PASS |
| Czas z przyszłości, przestarzała predykcja, spóźniony worker | `TestChecks.test_future_stale_late_and_synthetic`, `TestCoordinatorQuant.test_required_missing_quant_blocks_and_future_time_is_not_fresh`, `TestScheduler` | PASS |
| Złe jednostki, NaN/Inf/bool, rozkład spoza zakresu | `TestChecks.test_contract_errors_never_reach_features` | PASS |
| Poprawne zero pozostaje zerem | `TestChecks.test_valid_zero_is_kept` | PASS |
| Brak wag / danych / DXY / newsów / order book / zależności | `TestService.test_runs_without_panel…`, `test_ui_quant.test_01` (przyczyny wykluczeń, reszta działa) | PASS |
| Alias TH_RF/TH_XGB/TH_SVM i Event GRU | `TestAliases` (oba testy), `TestInventoryCli.test_inventory_classifies_everything` | PASS |
| P(UP) vs P(TP2), różne TF / horyzonty / plany | `TestChecks.test_no_implicit_averaging_of_different_events`, `TestPlanSimulator.test_short_exits…` (nowy hash zadania) | PASS |
| Pusty zestaw gotowych modeli | `TestService.test_empty_model_set_is_not_trained_without_invented_value` | PASS |
| Foldy, OOF i kalibrator bez przyszłych etykiet | `TestMetaModel.test_no_level_sees_future_labels` | PASS |
| Nieznana prowizja / konwersja waluty | `TestUnitsEV.test_unknown_commission_or_currency_is_not_validated` | PASS |
| Spread w bid/ask bez podwójnego odjęcia | `TestUnitsEV.test_spread_in_prices_not_subtracted_twice`, `TestPlanSimulator.test_short_exits_on_ask…` | PASS |
| Partial TP, BE, timeout, luka | `TestPlanSimulator.test_partials_then_be_from_next_bar`, `test_timeout_gap_and_immature` | PASS |
| TP i SL w jednej świecy | `TestPlanSimulator.test_ambiguous_bar_policy_fixed_in_advance` | PASS |
| Save/load i zmiana schematu cech | `TestMetaModel.test_save_load_schema_and_rollback` | PASS |
| Zmiana instrumentu / modelu / danych i rollback | `TestMetaModel.test_save_load_schema_and_rollback`, `TestService.test_label_maturation…` (wiersze innego instrumentu nie są etykietowane) | PASS (zmiana rachunku: logika istniejącego bridge, bez nowego testu) |
| Zamknięty panel i wiele odczytów API | `TestService.test_runs_without_panel…`, `test_ui_quant.test_01` | PASS |
| Timeout, awaria zadania, przeciążenie | `TestScheduler.test_cycles_timeouts_failures_and_generations` | PASS (brak GPU i crash procesu workera: NOT_RUN – brak środowisk deep/Kronos w cyklu) |
| Quant wyłączony i SHADOW – zgodność | `TestCoordinatorQuant.test_off_and_shadow_parity` (identyczny werdykt, kody, hash wejść) | PASS |
| ASSIST oraz brak wyniku REQUIRED | `TestCoordinatorQuant.test_assist_can_only_hold`, `test_required_missing…`, `TestService.test_modes_assist_needs_validation…` | PASS |
| STOP, rezerwacje, równoległe ACTIVE/SH | istniejące `test_decision_arc_u6` (18) + `TestCoordinatorQuant.test_quant_has_no_order_path` | PASS |
| EV ręcznie: G=2R, L=1R, p=0,6 → 0,8R, p* = 1/3 | `TestUnitsEV.test_hand_computable_ev` | PASS |
| Wilson nie jest niepewnością p(x) | `test_evaluation.Engine.test_wilson_is_not_a_model_interval` | PASS |
| Rdzeń numeryczny | `TestNumeric.test_rolling_cov_metrics` | PASS |
| CLI `--help`, kody wyjścia, brak danych | `TestInventoryCli.test_cli_help_exit_codes_and_missing_data`, `test_ui_quant.test_04` | PASS |

## Dowody z działającego bota demo (SYNTHETIC)

- Cykl co 5 s bez otwartego panelu, 0 błędów w 24 cyklach.
- 15 wyników READY: reguły SH, wskaźniki, DXY, strefy, mikrostruktura, Kalman, breakout, multi-indicator, SMC, align mean, GPR.
- 7 wykluczonych z przyczyną: `.venv_kronos` / `.venv_candles` nie zainstalowane, MC na żądanie, brak artefaktów lab / Event GRU / scalp A.
- Wiersze ledgera powstają z kandydatów setupów (`rows_logged` > 0).

## NOT_RUN (wymaga środowiska, którego nie było)

| Pozycja | Powód |
|---|---|
| Trening i walidacja meta-modelu na danych rzeczywistych | brak terminala MT5 i danych użytkownika; ledger zbiera się dopiero po aktualizacji |
| Event GRU na żywo z artefaktem | brak wytrenowanego artefaktu `event_engine_dir3` (ścieżka sprawdzona: NOT_TRAINED z przyczyną) |
| Scalp A, gold_candles, Kronos w cyklu Quant | brak `.venv_candles` / `.venv_kronos` z wagami w kontenerze |
| Rodziny LSTM / GRU / PPO | brak `.venv_deep` (MISSING_DEPENDENCY) |
| Kalkulator P/L terminala (`order_calc_profit`) | brak MT5 |
| Windows / WebView2 / build EXE z nową wersją | brak Windows; paczka budowana istniejącym `tools/build_release.py` (krzyżowa kompilacja Go) |
