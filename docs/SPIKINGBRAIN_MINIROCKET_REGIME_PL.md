# PMW-UPD-09 – SpikingBrain Finance, MiniRocket V2, mapa reżimu, Market Behavior, SMMA(3), Z-Score

Stan: kod zaimplementowany i przetestowany na danych testowych (TEST_ONLY). Brak treningu na prawdziwych danych, brak oceny przewagi (edge), brak kompilacji native. Żaden element nie składa zleceń ani nie zmienia Execution Lock.

## Moduły
| Moduł | Plik | Rola |
|---|---|---|
| MQ_SPIKE_BRAIN_FINANCE_V1 | `lab/spike_brain.py` (+ `lab/autodiff.py`) | enkoder zdarzeń BAR_EVENT_V1 / QUOTE_EVENT_V1, adaptacyjny LIF, uwaga LINEAR/SLIDING/HYBRID, MoE top-1 z 4 ekspertów + ekspert wspólny; własna adaptacja – nie LLM SpikingBrain i nie M02 (LEGACY_RULE_ROUTED_SNN) |
| MQ_MINIROCKET_UNIVARIATE_V2 / MQ_MINIROCKET_RIDGE_V2 | `lab/minirocket_v2.py` | 9996 cech PPV (L=128, request 10000), ridge (dual ≤2048 / CG), kalibracja temperaturą, przedziały CALIBRATED_RESIDUAL_LOCATION_V1, format binarny dla MQL5 |
| Native MQL5 | `mql5/MiniRocketV2/` | transform/ridge/format `.mqh`, skrypty SelfTest/Fit/Infer/Benchmark, wskaźnik SHADOW (bez order_send) |
| MQ_REGIME_MULTI_V2 | `lab/market_v2.py` | ER i nachylenie n=8/20/50, histereza, oś zmienności wspólna z M11; siła dowodów ≠ prawdopodobieństwo |
| Market Behavior | `lab/market_v2.py` | pivoty (known po prawych świecach), ogon/uszczelnione kotwice/nogi FINAL, EQH/EQL, AMBIGUOUS_ORDER, jednostki (pips tylko z jawną definicją) |
| MQ_SMMA_HL3_V2, MQ_ZSCORE_V2 | `lab/market_v2.py` | kanał SMMA(3) i Z-Score INCLUSIVE_N / PREVIOUS_N z hipotezami H_MR/H_BO/H_TP |
| Runtime | `lab/market_service.py`, `lab/si_service.py` | przyrostowy stan per instrument/TF, checkpoint (restart nie liczy świecy drugi raz) |

## API (tylko odczyt; GET nie trenuje)
`/api/v1/structure-intelligence/regimes`, `/swings`, `/swings/{id}?as_of=`, `/smma`, `/zscore?mode=`, `/native-status`, `/model-diagnostics`; zadania `POST /jobs` z `kind=train` (`encoder`, `attention`, `transform`) i `kind=calibrate_market`.

## Polecenia (z katalogu `backend`)
```
python -m masterquo structure-intelligence calibrate-indicators --latest --profiles MQ_REGIME_MULTI_V2,STRUCTURE_CAUSAL_V2,MQ_SMMA_HL3_V2,MQ_ZSCORE_V2
python -m masterquo structure-intelligence train --latest --task STRUCTURE_MOVE_M1_V1 --families MQ_SPIKE_BRAIN_FINANCE_V1 --encoder BAR_EVENT_V1 --attention HYBRID --profile standard
python -m masterquo structure-intelligence train --latest --task STRUCTURE_MOVE_M1_V1 --families MQ_SPIKE_BRAIN_FINANCE_V1 --encoder QUOTE_EVENT_V1 --attention HYBRID --profile standard
python -m masterquo structure-intelligence train --latest --task STRUCTURE_MOVE_M1_V1 --families MQ_MINIROCKET_RIDGE_V2 --transform MQ_MINIROCKET_UNIVARIATE_V2 --profile standard
python -m masterquo structure-intelligence minirocket export-native --model-id <CANDIDATE_ID> --output ./exports/minirocket
python -m masterquo structure-intelligence minirocket parity --reference-version sktime==1.2.0
python -m masterquo structure-intelligence benchmark --families MQ_SPIKE_BRAIN_FINANCE_V1,MQ_MINIROCKET_RIDGE_V2 --profile cpu
```
Launcher: `26_STRUCTURE_INTELLIGENCE.bat` (pozycje menu 15–21).

## Native MQL5 – instalacja na Windows
1. `27_MINIROCKET_NATIVE.bat "<folder danych terminala>" "<ścieżka metaeditor64.exe>"` kopiuje źródła do `MQL5\Include\PMW`, `Scripts\PMW` i `Indicators\PMW`, a potem kompiluje je wykrytym MetaEditorem. Kompilację uznaje się za udaną tylko wtedy, gdy powstał nowy plik EX5; status trafia do `MQL5\Files\PMW\native_status.json`.
2. `minirocket export-fixture` → skopiuj `PMW_MR2_FIXTURE.bin` do `MQL5\Files\PMW\` i uruchom w terminalu skrypt `PMW_MR2_SelfTest`, a następnie `PMW_MR2_Benchmark`.
3. `minirocket export-native` → skopiuj `model.bin` do `MQL5\Files\PMW\` i dołącz wskaźnik `PMW_MR2_Indicator` do wykresu M1. Bot czyta jego wynik tylko wtedy, gdy ustawiono `MQ_MT5_FILES_DIR=<folder danych>\MQL5\Files`. Wynik jest wyłącznie porównaniem audytowym (SHADOW).

## Parytet (stan w tym środowisku)
- FIT_LAYOUT_PARITY i FROZEN_STATE_PARITY: **PASS** względem sktime 1.2.0 (numba 0.68, numpy 2.5.4). Porównano 40 okien × 9996 cech: zero rozbieżności liczników, PPV identyczne w float32 (fixture: `tests/fixtures/minirocket`).
- Fit na jednym oknie: różnice biasów na poziomie zaokrągleń (numba fastmath) – raportowane, nie ukrywane. FIT_RANDOM_SELECTION_PARITY: NOT_CLAIMED. Używam własnego, przenośnego generatora SplitMix64.
- NATIVE_COMPILED / NATIVE_EXECUTED / benchmark native: **NOT_RUN** – w środowisku budowy nie ma MetaEditora; nie powstał żaden plik EX5.

## Rollback
Nowe rodziny są tylko kandydatami. Wskaźnik SHADOW przestawia się wyłącznie ręcznie (`select` / `rollback`). Wyłączenie: nie wybieraj kandydatów 09. Stan sekcji rynku leży w `data/si_market_state/` – można go usunąć; odbuduje się z okna świec. Archiwa i dane użytkownika pozostają nietknięte.
