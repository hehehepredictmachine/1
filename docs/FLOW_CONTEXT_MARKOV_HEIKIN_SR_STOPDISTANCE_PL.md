# PMW-UPD-11 – Markov 3-stanowy i koszyki różnic, Heikin Flow, kanały S/R, StopDistance

Stan: kod zaimplementowany i przetestowany na danych TEST_ONLY. Brak treningu na prawdziwych danych, brak oceny przewagi (NO_VALIDATED_EDGE) i brak kompilacji native (NOT_COMPILED_NO_METAEDITOR). Moduły nie składają zleceń, nie przesuwają SL/TP1 (MID M5) i nie zmieniają Execution Lock.

## Moduły (`backend/masterquo/lab/flow_context/`)
| Profil | Plik | Najważniejsze reguły |
|---|---|---|
| MQ_MARKOV3_FLOW_V1 | `markov.py` | d=(C_t−C_{t−L})/point; tau=max(q33(abs(d)) z train, tick/point) zamrożone po Fit; Dirichlet alpha=1; ring 1000; cykl prekwencyjny (ocena przed aktualizacją); luka nie tworzy przejścia; rozkład stacjonarny przez układ równań (PERIODIC/REDUCIBLE/NON_UNIQUE), nigdy P^64 |
| MQ_MARKOV_DIFF_FLOW_V1 | `markov.py` | K=9 kwantyli train (side=right, scalanie duplikatów → K_effective); emisje stanu docelowego; momenty skumulowanej zmiany przez DP (sprawdzone pełną enumeracją ścieżek); wachlarz MC 2048 ścieżek; min. 30 emisji na stan, inaczej brak projekcji |
| MQ_HEIKIN_FLOW_V1 | `heikin.py`, `ma.py` | MA1 na surowym OHLC → HA (rekurencja na surowym HA) → MA2; 16 par EMA/SMA/SMMA/LWMA; PARTIAL_PREFIX_V1 (globalny EMA bez zmian); PARTIAL_STARTUP do 3·(P1+P2)+10; ceny syntetyczne |
| MQ_SR_CHANNELS_V1 | `sr_channels.py` | pivoty 10/10; kwalifikacja przez 290 świec od potwierdzenia; limit szerokości 5% zakresu 300 świec; score=20·pivoty+dotknięcia; zachłanny wybór bez nakładania (top 10, widoczne 6); archiwum as-of i zdarzenia |
| MQ_STOP_DISTANCE_V1 | `stop_distance.py` | zakres=(H−L)/point (bez luki – to nie ATR); średnia SMA/EMA FULL_SEED; sugestia=średnia×factor (w punktach); cena SL zaokrąglana na zewnątrz do tick size; tryb doradczy; kalibracja NEXT_BAR_RANGE_COVERAGE |
| FLOW_CONTEXT_MOVE_M1_V1 | `task.py` | etykiety rynkowe jak STRUCTURE_MOVE_M1_V1 (nigdy ceny Heikin); 31 cech FLOW_CONTEXT_V1 (Markov tylko z prefiksu); LOGREG/XGB + CLASS_FREQ; ablacje; holdout jednorazowo |

## Polecenia (z katalogu `backend`)
```
python -m masterquo flow-context audit --asset XAUUSD
python -m masterquo flow-context calibrate --latest --modules heikin,sr-channels,stopdistance
python -m masterquo flow-context train-markov --latest --models MQ_MARKOV3_FLOW_V1,MQ_MARKOV_DIFF_FLOW_V1
python -m masterquo flow-context dataset --latest --task FLOW_CONTEXT_MOVE_M1_V1
python -m masterquo flow-context train --latest --task FLOW_CONTEXT_MOVE_M1_V1 --families LOGREG,XGB --profile standard
python -m masterquo flow-context replay --latest --mode shadow
python -m masterquo flow-context native-parity
python -m masterquo flow-context benchmark --profile cpu
python -m masterquo flow-context report --latest
python -m masterquo flow-context evaluate-holdout --candidate-id <ID> --protocol-id SI-PROTO-1.0.0
```
Launcher: `28_FLOW_CONTEXT.bat`. Train-all: zadanie `flow_context` (runner; od PMW-UPD-14 16 zadań).

## API (tylko odczyt)
`/api/v1/flow-context`, `/flow-context/series`, `/channels?mode=CURRENT_MAP_FULL_WIDTH|HISTORY_AS_KNOWN&as_of=`, `/markov`, `/stopdistance?entry=&side=`, `/native`, `/models`. Zadania: `POST /api/v1/structure-intelligence/jobs` z `kind` = `flow_calibrate`, `flow_markov`, `flow_dataset` lub `flow_train`. Każda komórka snapshotu Structure Intelligence ma sekcję `flow`, a agent ma wiedzę F01–F09 (prompt 1.9.0).

## Native MQL5 (`mql5/FlowContext/`)
- `MQ_HeikinFlow.mq5` – ABI: 24 bufory i 7 wykresów (bufory 0–11 to świece, 12–15 kanoniczne OHLC dla CopyBuffer, 16–23 obliczeniowe).
- `MQ_StopDistance.mq5` – bufory 0/1/2 w punktach.
- `MQ_SRChannels.mq5` – 6 buforów najbliższych pasm.
- `MQ_FlowCollector.mq5` – eksport `PMW_FLOW_EXPORT.txt` z sumą SHA-256. Ustaw `InpBars=0`: parytet wymaga, by eksport zaczynał się od pierwszej świecy historii.
- `MQ_FlowSelfTest.mq5` – samotest wspólnego jądra MA (`PMW_FlowMA.mqh`).

Instalacja i kompilacja: `28_FLOW_CONTEXT.bat` → 11. Bot czyta eksport tylko przy ustawionym `MQ_MT5_FILES_DIR`; jest on wyłącznie porównaniem audytowym (SHADOW).

## Rollback
Profil kalibracji: poprzednie wersje leżą w `data/flow_context/<instrument>/profile_<ts>.json` (przywróć jako `profile.json`). Modele: `flow-context rollback`. Wyłączenie: nie wybieraj kandydatów i nie dopasowuj Markowa. Sekcje wtedy pokazują MODEL_MISSING, a wskaźniki deterministyczne działają dalej.
