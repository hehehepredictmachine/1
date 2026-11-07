# Architektura decyzji – przed (1.32) i po (1.33, PMW-ARC-1)

## Przed (1.32)

```
ACTIVE (S01–S12) ── engine/decision.build ── execution_permission ── execution/gateway.py ── order_send
                                      ▲ mode gate + risk/portfolio.check (odczyt)
SH (SCALPING/HEDGING) ── sh/service.evaluate ── arbitraż SH ── sh/executor.py ── order_send
                                      ▲ mode gate + risk/portfolio.check (odczyt)
modele: ML gate (ACTIVE), rodziny ASSIST tylko w SH, Kronos tylko w SH
```

Słabe punkty:
1. **Wspólny limit portfela sprawdzany niezależnie przez każdą ścieżkę** (check‑then‑act). Gdy dwie ścieżki zadziałają w tym samym oknie
   wysyłki, obie widzą wolne miejsce i obie wysyłają. Replay (`python -m masterquo.decision.replay`): limit 2 i 6 jednoczesnych
   żądań – w 1.32 przechodzi **6**, w 1.33 **2**.
2. Brak jednolitego zapisu decyzji obu ścieżek. ACTIVE zapisywał `decisions`, SH zapisywał `sh_signals`, w różnych kształtach i bez ról modeli.
3. Rola modelu zależała od ścieżki. Rodziny ASSIST działały tylko w SH, a roli „wymaganej” w ogóle nie było.
4. Idempotencja była osobno w każdym adapterze: `order_attempts.entry_key` i `sh_actions`. Nie istniał wspólny rejestr intencji wykonania,
   który rekonsyliacja UNKNOWN domykałaby dla obu ścieżek.

## Po (1.33)

```
                       ┌──────────── DecisionCoordinator (decision/coordinator.py) ────────────┐
ACTIVE candidate ─────▶│ StrategyCandidate → bramki ścieżki → role modeli → DecisionRecord     │
SH candidate ─────────▶│ OBSERVE (bez wpływu) / ASSIST (tylko wstrzymanie) / REQUIRED (warunek) │
                       └───────────────┬───────────────────────────────────────────────────────┘
                                       ▼
                     IntentLedger + RiskBook (decision/ledger.py) – jedna bramka NOWEGO wejścia
                     ExecutionIntent (dedup) → rezerwacja atomowa (BEGIN IMMEDIATE) → SENT → outcome
                                       ▼                                    ▼
                         execution/gateway.py (ACTIVE)            sh/executor.py (SH)
                                       ▼                                    ▼
                         PositionManager._resolve_unknown        SHService.recover (ENTRY_UNKNOWN)
                                       └──────────── IntentLedger.sync() ───┘
```

* Kontrakty: `decision/contracts.py`, 10 rekordów (InstrumentSpec, ObservationEvent, MarketSnapshot, FeatureSet, MarketContext,
  ModelForecast, StrategyCandidate, DecisionRecord, ExecutionIntent, ExecutionOutcome). Każdy jest sprawdzany pole po polu:
  nieznane pole, brak pola, zły typ, NaN/Inf lub wartość spoza enumeracji powodują odrzucenie.
* Migracja `0025_decision_arc.sql` jest addytywna: tabele `decision_records`, `execution_intents` i `risk_reservations`. Wersja 1.32
  ich nie czyta, więc rollback binarki nie wymaga cofania bazy.
* Zakres celowo zachowany: SIGNALS / PAPER / AUTO DEMO / AUTO LIVE, przycisk STOP, limity użytkownika, wymagania brokera, osobne
  adaptery wykonania (magic/komentarze), zarządzanie istniejącymi pozycjami (nigdy nie wymaga rezerwacji).
* Wycofana Execution Lock z 1.14 nie wraca. Rezerwacja nie jest blokadą wykonania: odmawia tylko nowego wejścia przekraczającego
  limit wybrany przez użytkownika i zawsze podaje powód.

## Gdzie co jest podłączone

| Element | Plik | Punkt w przepływie |
|---|---|---|
| Węzeł `MODELS` drzewa decyzji ACTIVE | `engine/decision.py` (`model_gate`) | przed hashem decyzji, więc karta sygnału, `decision_id` i zapis są spójne |
| Rekord decyzji ACTIVE | `engine/service.py` → `arc.record_active` | przy każdej nowej treści decyzji |
| Rekord decyzji SH + REQUIRED | `sh/service.py` (`evaluate`) | po odbiornikach rodzin/Kronos i arbitrażu, przed `persist_signal` |
| Intencja + rezerwacja ACTIVE | `execution/gateway.py` (`execute`) | po walidacji, przed `order_attempts` i wysyłką |
| Intencja + rezerwacja SH | `sh/service.py` (`open_plan`) | przed `create_plan` i `ex.open` |
| Rozliczanie UNKNOWN | `execution/manager.py` (`tick`) → `arc.sync()` | co sekundę; czyta wyniki rekonsyliacji obu adapterów |
| API | `GET /api/v1/decision/status`, `GET /api/v1/decision/records/{id}` | panel / diagnostyka |
| Replay | `python -m masterquo.decision.replay [--db kopia.sqlite] [--required ...]` | porównanie starej i nowej logiki |
