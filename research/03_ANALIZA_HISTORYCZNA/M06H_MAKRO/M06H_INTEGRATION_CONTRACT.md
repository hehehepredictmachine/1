# M06H v1.0.0 — kontrakt integracyjny (bez modyfikacji oryginalnego M06)

```text
M04N (Fed/BLS/FF/MM) ── cykliczny REPORT.json ── M06H_ARCHIVE_WATCH ── JSONL hash chain
M01 / MT5 DEMO ─────── copy_rates_range, UTC ──────── CSV closed M1 bars
M07/M03E/M10A/M14 ── osobny historyczny point-in-time ledger sygnałów
MT5 history ticks (M06H_EXPORT_MT5_TICKS_READONLY.py) + profil kosztów M11 ── M06 packet (opcjonalnie)
                                                     ↓
                 M06H_RESEARCH_ENGINE -> event-study + source clock quality
                                      -> M06_REFERENCE_ENGINE (oryginał; opcjonalnie)
                                      -> porównanie news-filter versus baseline
                                      -> M06H_VALIDATION_REPORT.json / M06H_REPORT_PL.md
```

## Obowiązkowe wejścia

- `bars.csv`: `symbol,time_utc,open,high,low,close,bar_state=CLOSED`, opcjonalne `tick_volume,real_volume,spread_points`. `time_utc` jest początkiem baru UTC (`time` MT5); zamknięcie dostępne minutę później. Świece nie mogą być przemieszane, zdublowane ani błędne OHLC; wszystkie punkty muszą odpowiadać `symbol` w zamrożonej konfiguracji.
- `events`: **preferowany** `M04N_HISTORY.jsonl` z kolejnymi raportami M04N i czasem przechwycenia; alternatywnie jeden `M04N_INTELLIGENCE.json` wyłącznie do diagnostyki jednego momentu. Jeśli masz oddzielnie weryfikowane historyczne kalendarze, użyj `{"kind":"CURATED_HISTORICAL_EVENTS","data_provenance":"USER_SUPPLIED","events":[...]}` i wymagaj prawidłowego `known_at` — nadal bez poświadczenia autentyczności.
- `config.json`: `frozen=true`, `research_only=true`, symbol, `horizons_minutes`, `guard_windows_minutes`, minimalne N, `bootstrap_iterations` + seed i niepokrywające się `folds` z `FINAL_OOS`.
- **Opcjonalny packet M06:** oryginalny kontrakt M06, historyczny signal ledger i ticki. Konta Zero NIE utożsamiać z zero prowizji, zero spreadu czy zero slippage. Foldy identyczne z M06H.

## Semantyka czasu (bez lookahead)

Dla zdarzenia kalendarzowego `scheduled_at=t` i przechwyconego raportu `captured_at=c`:
- `known_at = max(source.available_at, c)`, a przy zmianie oceny wpływu także `impact_known_at`.
- W symulacji blokady setupu w chwili `decision_at` zdarzenie może blokować tylko gdy `known_at<=decision_at` i `impact_known_at<=decision_at`. Dane `SYNTHETIC` nie blokują prawdziwych sygnałów.
- Jeśli ta sama publikacja otrzymała sprzeczne godziny tego samego dnia, jest wykluczana z event study i symulacji guard zamiast arbitralnego wyboru późniejszej wersji.
- Przy cenach świec z MT5 dla `event_at=t`, pomiar startuje od M1 **zamkniętej nie później niż `t−1m`**, nie używa świecy obejmującej zdarzenie. Punkt końcowy to dokładne M1 `close_at=t+h`, bez imputacji i bez interpolacji braków.
- Przy replay transakcji oryginalny M06 wymaga pierwszego ticka **późniejszego** niż dostępność sygnału. Dla LONG `ask` wejścia/`bid` wyjścia; SHORT odwrotnie, ze slippage i prowizją.

## Wyjścia

`runtime_m06h/M06H_VALIDATION_REPORT.json`:
- `event_study.event_rows[]`: czas, źródło, fold, horizon, bp, matched control, `synthetic`; to **nie** są poziomy Entry/SL/TP.
- `event_study.aggregates[]`: n, mediana abs bp, liczba par, excess abs bp i bootstrap day-block CI (jeśli wystarczają niezależne dni).
- `strategy_validation`: `NOT_RUN` bez packet; w przeciwnym razie replay oryginalnym M06, `fold_comparison[]`, `by_strategy_by_fold[]`, `signal_decisions[]`, `m06_cost_stress_scenarios[]`, `reason_codes`.
- `approval_status=PENDING_APPROVAL`, `execution_permission=BLOCKED`, `live_execution_allowed=false`, `orders_sent=0`. **Brak możliwości podniesienia uprawnień**.

## Ograniczenia

Niespójny lub za krótki snapshot M04N nie zastępuje pełnej bazy wydarzeń 2025. Badanie wielu horyzontów bez wielokrotnej korekty nie potwierdza statystycznie przewagi; CI opisuje jedynie badane próbki. OOS tylko po zamrożeniu protokołu; forward MT5 DEMO i kontrole M01/M08/M11/M14 nadal wymagane. Wszystkie silniki M01–M16 bez zmian.
