# Postęp przebudowy architektury decyzji (ARC, 1.33 U6)

| Wymaganie | Stan | Dowód |
|---|---|---|
| 10 kontraktów typowanych | wykonane | `decision/contracts.py`; `TestContracts` |
| role OBSERVE / ASSIST / REQUIRED | wykonane, obie ścieżki | `coordinator.evaluate_models`; węzeł `MODELS` (ACTIVE); `sh/service.evaluate` (SH) |
| jeden Decision Coordinator | wykonane | `DecisionCoordinator` w `runtime.py`, wspólny dla engine/gateway/SH/manager |
| DecisionRecord dla obu ścieżek | wykonane | tabela `decision_records`, API `/api/v1/decision/*` |
| wspólny portfel/ryzyko z atomową rezerwacją | wykonane | `RiskBook.reserve` (BEGIN IMMEDIATE); test 8 wątków |
| jedna bramka wykonania nowego wejścia: intencje, dedup, UNKNOWN → rekonsyliacja | wykonane jako jedna bramka logiczna (ledger) przed dwoma adapterami MT5 | `IntentLedger`; testy na FakeMT5 i SH PAPER |
| replay stary vs nowy | wykonane | `python -m masterquo.decision.replay`; `TestReplay` |
| brak powrotu Execution Lock, tryby i STOP bez zmian | zachowane | `test_execution_lock_withdrawn` OK |

Decyzja projektowa: dwa adaptery MT5 (ACTIVE i SH) zostają osobne. Mają różne magic/komentarze, maszyny stanów i rekonsyliację, które
były już przetestowane. Scalenie ich w jeden kod wysyłki oznaczałoby przepisanie przetestowanych ścieżek bez zysku dla bezpieczeństwa.
Wspólna jest bramka, przez którą musi przejść każde **nowe** wejście: intencja, deduplikacja, rezerwacja i rozliczenie wyniku.

Regresja po U6 (uruchomione):
* `test_decision_arc_u6` 18 OK;
* `test_risk_execution` 21 OK (oczekiwana lista migracji uzupełniona o 0025);
* `test_sh_service` 13, `test_sh_risk_state` 14, `test_execution_lock_withdrawn` 11, `test_bridge_engine` 17, `test_active_pipeline` 3,
  `test_pipeline` 3, `test_signal_view` 6, `test_kronos_bot` 17, `test_evaluation` 25, `test_arch_fixes` 11, `test_zones` 42 – wszystkie OK;
* `test_structure_intelligence` 21, `test_telegram` 6, `test_families_u4` 18, `test_indicators_u2` 30, `test_plans_svp_u3` 21,
  `test_studio_u5` 7 – wszystkie OK;
* `test_kronos_runtime`: 8 pominiętych (wymaga środowiska Kronos).

Uruchomienie demo (`serve --demo`): `/api/v1/decision/status` zwraca rekordy ścieżki ACTIVE.
