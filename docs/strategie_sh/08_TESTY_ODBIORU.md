# PMW-SH-1 · Testy odbioru 1–16

Wszystkie testy działają na symulacji: PAPER, symulator terminala (FakeMT5) albo prawdziwy proces serwera z `--demo`. **Żaden
test nie dotyka rachunku rzeczywistego ani nie publikuje sygnałów na zewnątrz.** Testy z prawdziwym MT5 klienta są
zablokowane (B-MT5). Symulacja i integracja z prawdziwym terminalem są rozdzielone: `executor` ma tę samą ścieżkę
`order_send` dla symulatora i dla MT5, a testy pokrywają tylko symulator.

Łącznie 67 testów w 7 plikach `tests/test_sh_*.py`; wynik pełnej regresji jest w raporcie końcowym.

| # | Wymaganie | Test(y) |
|---|---|---|
| 1 | jednostki TP BUY/SELL (USD, tick, od fill) | `test_sh_core` (units), `test_sh_setup.Setup.test_buy_ready_targets_from_ask / test_sell_ready_targets_from_bid`, `test_sh_service.PaperScalping.test_full_cycle… / test_sell_targets…` |
| 2 | partiale i krok wolumenu | `test_sh_core` (split), `test_sh_risk_state.Risk.test_sizing_from_sl_distance / test_fallback_two_legs_and_infeasible`, `test_sh_service.PaperScalping.test_infeasible_partial_fill_closes` |
| 3 | BE po potwierdzonym TP2 | `test_sh_service.PaperScalping.test_full_cycle_be_after_confirmed_tp2`, `test_sh_core` (lifecycle) |
| 4 | odrzucenie modyfikacji SL | `test_sh_service.DemoTerminal.test_open_partials_be_reject_and_restart`, `test_sh_risk_state.Executor.test_paper_modify_rejected_beyond_price`, `test_sh_core` |
| 5 | luka | `test_sh_service.PaperScalping.test_gap_through_stop_fills_worse`, `test_sh_core.GapThroughAllTargets`, `test_sh_training.ReplayMechanics` |
| 6 | idempotencja ponowień | `test_sh_risk_state.Store.test_action_idempotency_and_owner`, `Executor.test_demo_open_partial_modify_idempotent`, `test_rejection_and_unknown_not_resent`, `test_sh_service` (powtórzona cena) |
| 7 | konflikty | `test_sh_risk_state.Coordinator.test_matrix`, `test_sh_setup.Setup.test_htf_conflict_waits` |
| 8 | nieaktualne dane, brak modelu, zły schemat | `test_sh_setup.Setup.test_stale_data_blocks`, `Registry.test_limited_mode_without_event_model`, `TpModel` (INCOMPATIBLE), `test_sh_fixes` (integralność / schemat ML) |
| 9 | rozłączenie / restart z otwartymi pozycjami | `test_sh_service.DemoTerminal.test_open_partials_be_reject_and_restart`, `test_unknown_entry_adopted_and_orphan_reported`, `test_sh_risk_state.Store.test_plan_once_per_signal_and_fsm_roundtrip` |
| 10 | odrzucenie hedge i częściowe wykonania | `test_sh_service.DemoTerminal.test_hedge_rejected_stays_unhedged`, `test_sh_core` (hedge FSM: partial fill) |
| 11 | HEDGING na niezgodnym rachunku | `test_sh_risk_state.Risk.test_hedging_blocked_on_netting_account`, `test_sh_service.PaperHedgingNetting` |
| 12 | rozliczenie koszyka | `test_sh_service.PaperHedging.test_hedge_unwind_and_basket_accounting`, `ManualClose`, `test_sh_core` |
| 13 | eksport i odtworzenie treningu | `test_sh_training.ExportImportPromote.test_package_roundtrip_no_secrets`, `RunnerSHModels` (runner + `sh train`) |
| 14 | postęp, anulowanie, awaria treningu | `test_sh_training.PanelStatuses` (postęp rzeczywisty, UTRACONY_PROCES, CANCELLED), istniejące `test_train_all.TestCancelResume` |
| 15 | zgodność importu, promocja, rollback | `test_sh_training.ExportImportPromote` (import jako kandydat, odrzucenie sum, promocja / rollback), `test_sh_setup.TpModel` |
| 16 | panel na prawdziwych endpointach | `test_sh_api` (proces serwera + Chromium 1366/390 px, bez błędów strony, bez zmiany trybu) |

## Błędy znalezione przez testy w tym etapie (naprawione)

* **Bramka modelu zdarzenia** przepuszczała model z czystego szumu (Brier < bazowy przypadkiem). Naprawa: istotność > 2 SE.
* **Luka przez TP1–TP3** zlecała zamknięcie runnera pełnym pozostałym wolumenem, zanim wykonały się partiale. Na terminalu
  dałoby to próbę zamknięcia większego wolumenu niż pozycja. Naprawa: runner = pozostało − oczekujące partiale.
