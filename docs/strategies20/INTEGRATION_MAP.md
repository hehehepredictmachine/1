# Mapa integracji pakietu 20 strategii (rzeczywiste punkty wywołań)

Jeden przepływ – bez nowej aplikacji i bez drugiego robota:

```
MT5 bridge (zamknięte świece M1/M3/M5/M15/H1, notowanie)          backend/masterquo/mt5/bridge.py  (M3: natywne albo pełne trójki M1)
  -> SHService._tick -> cycle()  (raz na zamkniętą M1)               sh/service.py
       legacy SCALPING / HEDGING (bez zmian)                          sh/setup.py
       pack_cycle() -> PackEngine.evaluate()                          sh/pack/engine.py  (jedna generacja cech na TF i cykl)
            detectors.detect (BUY + lustrzany SELL)                   sh/pack/detectors.py, features.py
            solver.solve (TP1/TP2, RR netto, RR koszyka)              sh/pack/solver.py
            policies.hedge_loss_bound / texts (HG)                    sh/pack/policies.py
       odbiorniki modeli na READY: Kronos, Chronos-2/FinCast,         sh/service.py _kronos/_tsfm, modelhub/families (role rodziny)
       rodziny modeli (tylko READY -> WAIT)
       arbitrate() – jedno wejście na ekspozycję, klucz signal_id      sh/coordinator.py
       RK.evaluate() z profilem wariantu + pack_risk_extra()          sh/risk.py, sh/service.py
       DecisionCoordinator.record_sh (strategy_id wariantu)           decision/coordinator.py (by_source)
       persist_signal (READY + koniec gotowości; WAIT tylko w pamięci) sh/store.py (sh_signals.strategy_id, signal_tf)
       open_plan -> IntentLedger/RiskBook (ENTRY) -> SHExecutor        decision/ledger.py, sh/executor.py
       bind_fill_pack (planowane TP1/TP2, kontrola poślizgu)          sh/service.py
  -> manage() co tick: Position / Basket                              sh/lifecycle.py, sh/hedge_fsm.py (Basket.policy)
       pack_hedge_step: limit ratio po partialu, polityka wariantu,    sh/service.py, sh/pack/policies.py
       HEDGE intent (IntentLedger kind=HEDGE + rezerwacja RiskBook)
  -> plan PMW-PLAN-2 -> API -> wykresy / rejestr sygnałów             plans/contract.py from_pack, plans/service.py collect_pack
```

| Obszar | Plik / funkcja | Co zmieniono |
|---|---|---|
| Katalog i konfiguracja | `sh/pack/catalog.py`, `config/sh_strategy_pack_v2.json` | 20 definicji, parametry, hash wariantu, override z walidacją, status walidacji |
| Tożsamość | migracja `db/migrations/0027_sh_pack.sql` | `strategy_id`, `signal_tf` w `sh_signals` i `sh_plans`; stare wiersze = `LEGACY_SCALPING` / `LEGACY_HEDGING` |
| Arbitraż | `sh/coordinator.py arbitrate` | klucz `signal_id`; priorytet: rodzina → klaster → RR netto → ID; przeciwne kierunki → WAIT |
| Koordynator decyzji | `decision/coordinator.py sh_candidate` | `strategy_id` wariantu (wcześniej nazwa rodziny), `by_source` dla 20 rekordów w cyklu |
| Ledger | `decision/contracts.py`, `decision/ledger.py` | `ExecutionIntent.kind` = `ENTRY` / `HEDGE`; noga hedge rezerwuje zasób RiskBook |
| Ryzyko | `sh/risk.py` (bez zmian logiki) + `SHService.pack_risk_extra` | profil wariantu (dwa udziały, brak fallbacku, limity hedge), `PARTIAL_VOLUME_INFEASIBLE`, `HEDGE_VOLUME_INFEASIBLE` |
| AUTO_LIVE | `SHService.pack_live_validation` | wymaga raportu wariantu `VALIDATED` na `REAL_USER_DATA` |
| Cykl hedge | `sh/hedge_fsm.Basket.policy`, `SHService.pack_hedge_step` | ogólny trigger/unwind wyłączony dla planów pakietu; polityka wariantu; timeout hedge = wyjście koszyka; STOP blokuje nowy hedge, nie wyjścia |
| Porównanie kosztów | `SHService.pack_hedge_step` | stary błąd (limit kosztu przekazywany jako koszt redukcji) pozostaje tylko w legacy `hedge_step`; pakiet nie używa tej reguły – porównanie HEDGE / REDUCE / NO_HEDGE jest w replayu na tych samych wejściach |
| Plan wykresu | `plans/contract.py from_pack`, `plans/service.py collect_pack` | PMW-PLAN-2: TP1/TP2 (bez TP3), strzałka, klucze poziomów, RR, koszty, hedge |
| API | `api/app.py` | `/api/v1/sh/strategies` (+`/config`), `/api/v1/sh/pack/evaluations`, `/api/v1/sh/signals?strategy_id&tf&symbol`, `/api/v1/plans/chart?layer=PACK&family&strategy_id&tf&plan_id&symbol`, `/api/v1/sh/chart?tf=M3` |
| UI | `components/PackPanel.tsx` (strona Strategie), `features/pmw133/overlays.tsx` (warstwa „Pakiet 20”), `features/towers/signals.ts`, `SignalTower.tsx`, `SignalChart.tsx`, `WtcTower.tsx`, `features/towers/data.ts`, `usePoll.ts` | panel 20 wariantów, strzałki, filtry, M3, tożsamość wariantu w rejestrze sygnałów, poziomy SH z planu, token generacji |
| Historia | `bridge.required_bars` (`runtime.py`) | H1 1050, M1 900, M5 700, M3 500, M15 400 zamkniętych świec |
| Replay / trening | `sh/pack/replay.py`, `sh/train_cli.py pack-replay`, `training/runner.py t_sh_pack`, `studio/registry.py`, `39_PAKIET_20_WALIDACJA.bat` | walk-forward na eksporcie centrum treningu; werdykt per wariant |

**Modele:** pakiet nie uruchamia żadnej inferencji – czyta istniejące konteksty (Kronos, Chronos-2, FinCast, rodziny) z ich rolami
rodziny SCALPING / HEDGING (OBSERVE / ASSIST / REQUIRED). `sh_tp_model` (TP2 = 3 USD, trzy części) jest oznaczony jako **niezgodny** ze
zdarzeniami pakietu i nie ocenia nowych planów; `p_tp1_before_sl`, `p_tp2_before_sl`, `p_net_positive`, `expected_net_r` = `null` z powodem.

**Czego nie zmieniono:** S01–S12 (bez nowych ID i bez zmiany zachowania), legacy SCALPING/HEDGING (te same reguły, trzy TP, BE po TP2),
tryby wykonania, STOP, limity ryzyka, rekonsyliacja, właściciel pozycji, wygląd menu.
