# M06 v1.0.0 — Kontrakt integracji (kandydat, bez wdrożenia)

## Granice projektu

M06 jest właścicielem **raportu walidacji**, nie polityki wykonania, strategii ani sygnału. Moduły M00–M05 oraz M07–M16 pozostają bez zmian. Status: `PENDING APPROVAL`.

```text
terminal.exe / terminal64.exe (MT5)
  → M01 DATA_SNAPSHOT: instrument, quotes/ticks, timestamp, broker/account/source metadata
  → M02 MARKET_STATE: snapshot_id, as_of, regime and point-in-time features
  → M03 MARKET_EVIDENCE: confirmed historical structure and setup evidence
  → M04 CONTEXT: session/calendar/DXY available-at information
  → M05 HISTORICAL_RESULT / M05P: preregistered predictions and analogues
  → M06 VALIDATION_REPORT (research only)
  → M08 evidence registry / M09 strategy router / M11 costs / M14 hard gates / M15 output
M16 supervisor status + durable event log informs historical reliability.
TradingView authenticated alerts: supplementary marked features only.
No screenshot/OCR, no TradingView-derived bid/ask fills, no order_send.
```

## Minimalny JSON wejściowy kodu referencyjnego

- `schema_version`: `2.0.0`.
- `data_snapshot`: `snapshot_id`, `dataset_id`, `as_of` ISO UTC, `data_source_policy="MT5_PRIMARY_TV_SUPPLEMENTAL_NO_SCREENSHOTS"`, `visual_capture_enabled=false`, `analysis_gate.status=PASS|PASS_WITH_LIMITATIONS`.
- `market_state`: `snapshot_id` i `as_of` identyczne z M01; `analysis_gate` jak wyżej.
- `account`: `account_type=ZERO_SPREAD`, `broker`, `account_id_hash` (**bez loginu/hasła**), `symbol`, `currency`, `commission_source` BROKER_DEALS/BROKER_TARIFF/SCENARIO_ONLY, `commission_per_lot_side`, `conversion_source`, `money_per_price_unit_per_lot`, `slippage_price`, opcjonalnie `swap_per_lot_per_overnight`.
- `validation_profile`: `max_entry_wait_seconds`, `bootstrap_iterations/seed`, `confidence_level`, `min_completed_oos_trades`, `acceptance_criteria_frozen=true`, `forward_demo_required=true`, `folds`: niepokrywające się `id,role,start,end` (end exclusive); minimum jeden fold.
- `trial_ledger`: co najmniej jeden prerejestrowany wpis z id/spec_hash.
- `ticks`: uporządkowane rosnąco `time`, `available_at`, `source_id="MT5..."`, `symbol`, `bid`, `ask`. Informacja o pochodzeniu jest etykietą dostarczoną przez adapter, nie potwierdzeniem podłączenia.
- `signals`: `signal_id`, `strategy_version`, `spec_hash`, `source=MT5_DERIVED`, `symbol`, `bar_state=CLOSED`, `signal_at`, `available_at`, `feature_available_at[]`, `side=LONG|SHORT`, `entry_type=MARKET_NEXT_AVAILABLE_TICK`, `stop`, `target`, `lots`, `max_hold_seconds`.

## Wewnętrzna arytmetyka

Dla LONG: wejście = ask + slippage_price; wyjście = bid - slippage_price. Dla SHORT: wejście = bid - slippage_price; wyjście = ask + slippage_price. Przy `money_per_price_unit_per_lot = M` i pozycji `lots=L`: gross LONG `(exit-entry)*M*L`, gross SHORT `(entry-exit)*M*L`; net = gross - commission(entry+exit) - swap. NIE odejmuj spreadu ponownie. Wartość `M` MUSI być zweryfikowana na brokerze; synthetic fixture używa wartości przykładowej.

Pierwszy obserwowalny tick o timestampie **późniejszym** niż dostępność sygnału może być wejściem, jeżeli mieści się w maksymalnym oczekiwaniu. Stop/target na kolejnych prawidłowych tickach według strony bid/ask. Brak ticka na końcu horyzontu → `UNRESOLVED`, nigdy założone zamknięcie. Brak swap przy overnight → `COST_UNKNOWN`, nie 0. Label przekraczający fold → `PURGED_BOUNDARY`, nie zaliczaj go do metryk folda.

## Zgodność z M05

M05 bada podobieństwa i rozkład historycznych zwrotów BRUTTO. M06 nie zamienia automatycznie tych procentów na P_TP_BEFORE_SL ani LIVE eligibility. Do niezależnej walidacji M05P wymagane są archiwalne snapshoty prognoz i ich rozstrzygniętych labeli. Prawdopodobieństwa z M05 muszą być skalibrowane osobnym eksperymentem; referencyjny M06 tego jeszcze nie implementuje.

## Wynik

`run_status=COMPLETED/FAILED`, `status=PASS_WITH_LIMITATIONS/PENDING/FAIL`, `metrics_by_fold`, `bootstrap`, `net_metrics`, `trades`, `cost_scenarios`, `validation.approval_status=RESEARCH_ONLY`, `validation.executive_live_eligible=false`, `reason_codes`, `trial_ledger`, `execution_permission=BLOCKED`. W upstream nie zmienia statusu M08.

**UWAGA:** `pass` testu syntetycznego nie potwierdza ekonomicznej przewagi, historycznego realizmu ani działania rachunku Zero. Rzeczywiste dane MT5 i weryfikacja taryfy brokera są wymagane.

## Komendy lokalne

```powershell
python M06_TESTS.py
python M06_REFERENCE_ENGINE.py --input M06_SYNTHETIC_INPUT.json --output M06_SYNTHETIC_OUTPUT.json
```

## Źródła techniczne

- [MT5 — bars, indeks 0 oznacza świecę bieżącą](https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesfrompos_py)
- [MT5 — copy ticks](https://www.mql5.com/en/docs/python_metatrader5/mt5copyticksfrom_py)
- [MT5 — historia deals](https://www.mql5.com/en/docs/python_metatrader5/mt5historydealsget_py)
- [MT5 tester, prowizje](https://www.metatrader5.com/en/terminal/help/algotrading/testing)
- [MT5 real ticks, floating spread](https://www.metatrader5.com/en/terminal/help/algotrading/tick_generation)

## Opcjonalne zebranie warunków z rachunku Zero

`M06_MT5_ZERO_ACCOUNT_PROBE.py` to oddzielny, **read-only** program, wymagający MT5 na Windows i biblioteki MetaTrader5. Zbiera jednorazową obserwację spreadu Bid/Ask, parametrów XAUUSD oraz historię prowizji/swap z dealów; nie zapisuje numeru konta ani ticketów i nie wysyła żadnych zleceń. Brak historii nie dowodzi braku prowizji. Wyjście `OBSERVED_NOT_CERTIFIED` nie oznacza walidacji taryfy brokerskiej.
