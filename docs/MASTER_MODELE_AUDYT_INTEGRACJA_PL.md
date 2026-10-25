# Master models (XXX.rar) – audyt, integracja i trening (PMW-MM, wersja 1.18.0)

Źródło zadania: `PEPEMARKETWIZARD_MASTER_MODEL_AUDIT_INTEGRATION_TRAINING_PROMPT.md` + paczka `XXX.rar` (11 specyfikacji).
Tryb pracy: SHADOW / OBSERVE. Żaden moduł z tej paczki nie składa, nie modyfikuje ani nie zamyka zleceń; Execution Lock, kill-switche i bramki ryzyka bez zmian.

## 1. Podsumowanie

* Powstał wspólny pakiet `backend/masterquo/mm/` (kontrakty, snapshot danych, splity chronologiczne z purge/embargo i jednorazowym holdoutem,
  rejestr cech/targetów, niezmienne artefakty z sha256, wskaźnik SHADOW z rollbackiem, ledger predykcji z dojrzewaniem etykiet, drift, orchestrator).
* Zaimplementowano 14 modułów ze specyfikacją (+ tablica dowodów jako warstwa integracji). 6 pozycji z listy master promptu nie ma specyfikacji w paczce –
  status `BLOCKED (SPEC_FILE_NOT_PROVIDED)`, algorytmów nie rekonstruowano z nazwy.
* Trening/ewaluacja wszystkich zadań działa w jednym orchestratorze (`python -m masterquo mm train`) i jako zadanie `master_models` wspólnego runnera treningu.
* Bot na żywo: `MMService` liczy na zamkniętych świecach M5 Align Mean, Kalman, strefy wybicia, robust volatility, Multi-Indicator, SMC i GPR
  (z ledgerem), pokazuje to w panelu Neural Cyberpunk → „12 Master Models” i agentowi (narzędzie `get_master_models`). Rola w SCALPING/HEDGING: `OBSERVATION`.
* Kod natywny MQL5: wskaźniki, EA bez handlu, self-test parytetu, OpenCL, benchmark Math Fidelity (3 silniki). Nieskompilowany – brak MetaEditora/terminala.
* Wszystkie przebiegi treningowe wykonano na danych **SYNTHETIC_TEST** (symulator terminala). Na takich danych żaden model nie przechodzi walidacji
  rynkowej i nie dostaje statusu VALIDATED_SHADOW. Brak dowodu przewagi rynkowej (`NO_VALIDATED_EDGE`).

## 2. Inwentarz źródeł

| # | Moduł | Specyfikacja w XXX.rar | Wersja kodu |
|---|---|---|---|
| 1 | Align Mean & Cross-Chart Visibility | AlignMean_HDC_SMC (A) | PMW-MM-ALIGNMEAN-1 |
| 2 | HDC (hiperwektory binarne) | AlignMean_HDC_SMC (B) | PMW-MM-HDC-1 |
| 3 | SMC BoS/CHOCH/IDM/FVG | AlignMean_HDC_SMC (C) | PMW-MM-SMCFVG-1 |
| 4 | BUZOA | BUZOA_Event_Driven (A) | PMW-MM-BUZOA-1 |
| 5 | SDOm | **brak** | BLOCKED |
| 6 | Event-Driven Engine + state stack | BUZOA_Event_Driven (B) | PMW-MM-EVENTENGINE-1 |
| 7 | STE-FlowNet (adaptacja finansowa) | STE_FlowNet_Financial_Event_Engine | PMW-MM-STEFLOW-1 |
| 8 | S3CE-Net / STFS | S3CE_NET_STFS | PMW-MM-STFS-1 |
| 9 | Quant Momentum (3 modele) | **brak** | BLOCKED |
| 10 | Native GPR XAUUSD | Native_GPR_XAUUSD | PMW-MM-GPR-1 |
| 11 | Kalman Filter Crossover | Kalman_Filter_Crossover_MQL5 | PMW-MM-KALMAN-1 |
| 12 | Renko Regression | **brak** | BLOCKED |
| 13 | Head & Shoulders | **brak** (istniejący detektor bez zmian) | BLOCKED |
| 14 | Multi-TF Data Grabber | **brak** (rolę pełni `training export`) | BLOCKED |
| 15 | Breakout Zones + Robust Volatility | Breakout_Zones_Robust_Volatility | PMW-MM-BREAKOUT-1 / ROBUSTVOL-1 |
| 16 | Tick Session Volume Profile | Tick_Session_Volume_Profile | PMW-MM-TSVP-1 |
| 17 | Multi-Indicator Strategy Pro | Multi_Indicator_Strategy_Pro | PMW-MM-MULTIIND-1 |
| 18 | Math Engine Fidelity Benchmark | Math_Fidelity_Benchmark | PMW-MM-MATHBENCH-1 |
| 19 | MT5 Chart Synchronization | **brak** | BLOCKED |
| 20 | Tablica dowodów (odkryta potrzeba, §8.2) | master prompt | PMW-MM-FUSION-1 |

Inwentarz jest w kodzie (`mm/inventory.py`), w API (`/api/v1/mm/status`) i w panelu.

## 3. Audyt stanu wyjściowego

* Wcześniej w repo: SMC BoS/CHoCH/IDM (`lab/context_ind/smc.py`, PMW-UPD-14) – **reużyty** jako silnik struktury dla kontynuacji FVG (bez duplikatu);
  Parabolic SAR (`scalp/indicators.py`) i Wilder RSI (`strategies/indicators.py`) – reużyte w Multi-Indicator; purged walk-forward (`lab/protocol.py`) – reużyty;
  autodiff numpy (`lab/autodiff.py`) – reużyty dla GRU/STE/STFS; detektor H&S (`analysis/chart_patterns.py`) – bez zmian; eksport historii – źródło snapshotów.
* Brakowało: wspólnych kontraktów wyjść modeli, ledgera SHADOW z dojrzewaniem etykiet, rejestru artefaktów z blokadą promocji, orchestratora zależności.
* Konflikty wykryte w specyfikacjach i rozstrzygnięte jawnie: SMC głębokość 73% (opis) vs 50% (diagram) – domyślnie 73%, 50% tylko jako jawny profil
  `DIAGRAM_50_UNRESOLVED`; siatka szumu GPR z artykułu kończy się na 0.1 przy standaryzowanym y – rozszerzona do 0.3/1/3 (zapisane `GRID_NOTE`,
  oryginał zachowany jako `ARTICLE_NOISE_GRID`); TSVP „wolumen” bez wolumenu transakcyjnego – tryb `TICK_ACTIVITY_PROXY` jawnie opisany jako proxy.

## 4. Mapa architektury

```
MT5 (bridge, zamknięte świece / ticki)         training export (snapshot + sha256)
        │                                                  │
        ▼                                                  ▼
  MMService.live()  ── closed M5 ──►  moduły deterministyczne   mm.orchestrator (16 zadań, graf zależności)
   │  align_mean, kalman, breakout, robust_vol, MI, SMC          │  snapshot → align/kalman/breakout/MI/SMC/TSVP
   │  GPR (fit + ledger "gpr_logret:LIVE", dojrzewanie)          │  → HDC / GPR / event engine(+STFS) / STE-FlowNet
   │  fusion.board (bez łączenia wyników)                        │  → BUZOA (bench + kalibracja Kalmana) → mathbench → board
   ▼                                                             ▼
 API /api/v1/mm/{status,live,job,ledger,rollback}      artefakty mm/artifacts/<model>/<id> (npz + manifest, sha256)
 Panel NC „12 Master Models”, agent get_master_models   SHADOW_ACTIVE.json (tylko VALIDATED_SHADOW, rollback)
 Rejestr SH (rola OBSERVATION → INFO/NONE)              LATEST_RUN.json, REPORT.json/md
                    ✗ brak ścieżki do gatewaya / order_send / ryzyka
```

## 5. Architektura treningu

* **Snapshot** (`mm/data.py`): katalog eksportu z `source_metadata.json` i `files_sha256` (weryfikacja przy otwarciu, `SNAPSHOT_HASH_MISMATCH`),
  `data_kind` = `REAL_USER_DATA` / `SYNTHETIC_TEST`, raport jakości per TF; brak wymaganych TF → `BLOCKED_DATA_QUALITY`.
* **Cechy/targety** (`mm/features.py`): rejestr 9 cech przyczynowych (zwroty, ATR rel., zakres, korpus, odległość od EMA20 w ATR, RSI14, tick volume rel.),
  `schema_id` w manifeście artefaktu; target 3-klasowy z pasmem 0.35·ATR·√h.
* **Splity** (`mm/splits.py`): chronologiczne train/val/test z purge = horyzont i embargo; `HoldoutGuard` otwiera test raz na kandydata (hash indeksów w manifeście).
* **Trenery**: HDC (akumulatory całkowite, online == rebuild), GPR (Matérn 3/2, siatka LML, transakcyjny refit), event engine (GRU + state stack + korelacja,
  kalibracja temperatury), STFS (strategia próbkowania, 0 parametrów), STE-FlowNet (dwupoziomowa korelacja + GRU + refinement), BUZOA (kalibracja Q/R Kalmana
  train→val, test raz). Moduły regułowe – ewaluacja (bez treningu).
* **Orchestrator** (`mm/orchestrator.py`): statusy QUEUED/RUNNING/SUCCEEDED/FAILED/CANCELLED/BLOCKED_DATA_QUALITY/BLOCKED_DEPENDENCY/NOT_APPLICABLE;
  błąd jednego zadania nie zatrzymuje niezależnych; status przebiegu CANCELLED > FAILED > BLOCKED_DATA_QUALITY > FINISHED_WITH_BLOCKED > FINISHED.
* **Rejestr artefaktów** (`mm/artifacts.py`): zapis atomowy (tmp + rename), nigdy nadpisanie, `allow_pickle=False`, kontrola instrumentu/schematu/sumy;
  statusy CANDIDATE / VALIDATION_FAILED / VALIDATED_SHADOW / TECHNICAL_TEST_ONLY (brak statusu LIVE). Na danych syntetycznych zawsze TECHNICAL_TEST_ONLY.
* **Ledger** (`mm/ledger.py`): jeden wiersz na predykcję (dedup przy restarcie), `matures_at ≥ available_at`, wynik dopisywany raz po dojrzeniu.
* **Drift** (`mm/drift.py`): PSI cech, dryf reszt, spadek pokrycia, wiek artefaktu → wyłącznie `SCHEDULE_CANDIDATE`.

## 6. Macierz statusów modułów

| Moduł | Kategoria | Python | MQL5 | Trening | Walidacja | Uwagi / blokery |
|---|---|---|---|---|---|---|
| Align Mean | DETERMINISTIC_INDICATOR | INTEGRATION_TESTED, SHADOW_OBSERVED (demo) | IMPLEMENTED | NOT_APPLICABLE | – | `PMW_AlignMean.mq5` (P&L tylko odczyt) |
| HDC | ONLINE_LEARNER | INTEGRATION_TESTED | IMPLEMENTED (`PMW_HDC.mqh`) | TRAINING_EXECUTED (synthetic) | nie | online == rebuild bit-exact |
| SMC FVG/IDM | RULE_STRATEGY | INTEGRATION_TESTED, SHADOW_OBSERVED | – (istniejący native SMC z UPD-14) | NOT_APPLICABLE | – | profil 73% domyślnie |
| BUZOA | OPTIMIZER | UNIT_TESTED, INTEGRATION_TESTED | – | NOT_APPLICABLE | – | słabszy od PSO/DE na funkcjach testowych |
| SDOm | OPTIMIZER | NOT_IMPLEMENTED | – | – | – | BLOCKED: brak specyfikacji |
| Event engine + stack | TRAINABLE | INTEGRATION_TESTED | IMPLEMENTED (`PMW_StateStack.mqh`, OpenCL) | TRAINING_EXECUTED (synthetic) | nie | OpenCL = parytet na POCL CPU |
| STE-FlowNet | TRAINABLE | INTEGRATION_TESTED | – | TRAINING_EXECUTED (synthetic) | nie | ≈ baseline zero |
| S3CE/STFS | TRAINABLE (strategia) | INTEGRATION_TESTED | – | TRAINING_EXECUTED (synthetic) | nie | SSAM/spiking backbone nie istnieje |
| Quant Momentum | TRAINABLE | NOT_IMPLEMENTED | – | – | – | BLOCKED: brak specyfikacji |
| GPR | TRAINABLE | INTEGRATION_TESTED, SHADOW_OBSERVED (demo, ledger) | IMPLEMENTED (wskaźnik + EA SHADOW) | TRAINING_EXECUTED (synthetic) | nie | kalibracja OK, MAE nie lepsze od zera |
| Kalman | RECURSIVE_FILTER | INTEGRATION_TESTED, SHADOW_OBSERVED | IMPLEMENTED (wskaźnik + EA SHADOW) | NOT_APPLICABLE (kalibracja Q/R osobno) | – | transliteracja MQL5: 0 różnic |
| Renko Regression | TRAINABLE | NOT_IMPLEMENTED | – | – | – | BLOCKED: brak specyfikacji |
| Head & Shoulders | DETERMINISTIC_INDICATOR | VERIFIED_IN_CODE (istniejący) | – | – | – | BLOCKED: brak nowej specyfikacji |
| Data Grabber | DATA_INFRA | VERIFIED_IN_CODE (`training export`) | – | – | – | BLOCKED: brak specyfikacji |
| Breakout Zones + Robust Vol | DETERMINISTIC_INDICATOR | INTEGRATION_TESTED, SHADOW_OBSERVED | IMPLEMENTED | NOT_APPLICABLE | – | transliteracja MQL5: 52 przebiegi, 0 różnic |
| TSVP | VISUALIZATION | UNIT_TESTED, INTEGRATION_TESTED | IMPLEMENTED | NOT_APPLICABLE | – | rebuild == inkrementalnie |
| Multi-Indicator | RULE_STRATEGY | INTEGRATION_TESTED, SHADOW_OBSERVED | – | NOT_APPLICABLE | – | dziennik + ablacje |
| Math Fidelity | BENCHMARK | UNIT_TESTED (Python + onnx/onnxruntime w osobnym venv) | IMPLEMENTED (3 silniki, EA, monitor, self-test) | NOT_APPLICABLE | – | MT5 runtime: BLOCKED (brak terminala) |
| Chart Sync | VISUALIZATION | NOT_IMPLEMENTED | – | – | – | BLOCKED: brak specyfikacji |
| Tablica dowodów | DATA_INFRA | INTEGRATION_TESTED, SHADOW_OBSERVED | – | NOT_APPLICABLE | – | bez głosowania, SAME_PRICE_FEED |

`SHADOW_OBSERVED (demo)` = odczyt na żywo w bocie widziany na symulatorze terminala w testach; obserwacji na rachunku użytkownika tu nie było.

## 7. Zmienione pliki

Nowe: `backend/masterquo/mm/` (contracts, data, splits, artifacts, ledger, drift, features, kalman, align_mean, robust_vol, breakout_zones, multi_indicator,
smc_fvg, tsvp, hdc, buzoa, gpr, events, stfs, event_engine, kernels/state_stack.cl, ste_flownet, mathbench, inventory, fusion, orchestrator, jobs, cli,
fixtures, service, knowledge), `mql5/MasterModels/` (Include/PMW: Kalman, GPR, HDC, StateStack, BreakoutCore, TSVPCore; Indicators: KalmanCross,
GPR_Forecast, BreakoutZones, TickSessionVP, AlignMean; Experts: KalmanShadowEA, GPR_ShadowEA; Scripts: PMW_MM_SelfTest), `mql5/MathFidelity/`
(Include: BenchmarkConfig, WeightLoader, MathEngineNative/Alglib/Onnx, BenchmarkStats; MathFidelityBenchmark_EA, FidelityMonitor, MathFidelity_SelfTest,
train_export_model.py, README.md), `frontend/src/nc/MasterModels.tsx`, `tests/test_mm_core.py`, `tests/test_mm_integration.py`, ten dokument.

Zmienione: `__main__.py` (komenda `mm`), `runtime.py` (MMService + dostawca dla agenta), `api/app.py` (5 endpointów `/api/v1/mm/*`),
`sh/models.py` (rola OBSERVATION, 9 wpisów mm_*), `training/runner.py` (zadanie `master_models`), `engine/service.py` (kontekst agenta),
`agent/tools.py` + prompt 2.1.0 + `agent/service.py` (wiedza MM-K01..K06), `frontend/src/nc/NeuralCyberpunk.tsx` (ekran 12), testy agenta/panelu/runnera,
wersja 1.18.0 (`version.py`, `build_release.py`, launcher, START_TUTAJ_TRENING_PL.md).

## 8. Przebiegi treningowe

Dane: eksport syntetyczny `XAUUSD-` z symulatora, 2026-07-26 → 2026-10-25 (M1 132 060, M5 26 412, M15 8 804 świec), `data_kind = SYNTHETIC_TEST`.

| Przebieg | Profil | Wynik |
|---|---|---|
| MMRUN-20261025T183142Z-f762ab | standard | 16/16 SUCCEEDED, 0 walidacji PASS, artefakty TECHNICAL_TEST_ONLY, wskaźnik SHADOW pusty |
| szybki przebieg w testach integracyjnych (eksport 2 mies.) | quick | 16/16 SUCCEEDED (test `test_all_jobs_and_labels`) |

Wybrane liczby (standard, dane syntetyczne – test techniczny, nie wynik rynkowy):

* **Kalman**: K ustalone iteracyjnie = analitycznie (0.8541 / 0.1461); replay == inkrementalnie; M5 2 058 przecięć, 858 whipsaw.
* **Kalibracja Kalmana (BUZOA)**: na walidacji wygrały parametry domyślne (BUZOA i random gorsze) → nic nie zmieniono.
* **GPR** (okno 120, h = 3×M5): walidacja n = 880, pokrycie 1σ 0.676 / 2σ 0.932; test (raz) n = 880, 1σ 0.682 / 2σ 0.944 (nominalnie 0.683 / 0.954);
  MAE 7.76e-4 vs zero 7.67e-4 → bramka „MAE nie gorsze od zera” **nie przeszła**.
* **HDC**: test n = 5 249, balanced accuracy 0.363 vs logreg 0.366, null (block-shuffle) 0.325; online == rebuild bit-exact; bramka „lepszy od logreg” nie przeszła.
* **Event engine**: test n = 1 649, wybrany wariant `no_stack`, log-loss 0.998 vs prior 0.997 – brak zysku; online vs offline max |Δp| = 4.9e-15 na 6 802 jednostkach;
  latencja (CPU) enkoder mediana 291 µs, korelacja stosu 9.7 µs, push 7.4 µs.
* **STFS**: na walidacji bez poprawy (log-loss 1.0219 vs 1.0209), ta sama liczba parametrów.
* **STE-FlowNet**: test MAE 1.160e-3 vs zero 1.156e-3 – brak zysku.
* **Breakout zones** (M5, 4 filtry): ~50% fałszywych wybić przy każdym filtrze (np. VWAP: 1 099 zaakceptowanych, false rate 0.501).
* **SMC 73%**: 124 wejścia, średnio +0.016 R (rozstrzygnięte); profil 50%: 204 wejścia, −0.092 R.
* **Multi-Indicator**: 1 376 zaakceptowanych sygnałów M5; udział TP wśród rozstrzygniętych 0.32 (pełny) – ablacje nie wskazują przewagi.
* **BUZOA vs PSO/DE/Random** (równy budżet, 5 ziaren, mediana): BUZOA lepszy od Random na wszystkich 15 funkcjach × wymiarach, gorszy od PSO na wszystkich 15,
  od DE na 14 z 15 (wyjątek: Rastrigin d10, 43.1 vs 49.8).
* **TSVP**: 6 500 ticków symulatora, rebuild == inkrementalnie (1 000 duplikatów z nakładających się odczytów zignorowanych).
* **Math Fidelity (Python)**: reload CSV == referencja (0.0), oczekiwany błąd float32 5.8e-7; onnx.checker PASS, onnxruntime max |Δ| 4.6e-7 (osobny venv).

## 9. Walk-forward / holdout

Wykonane wyłącznie na danych syntetycznych: chronologiczne splity z purge, wybór wariantu na walidacji, test otwarty raz (hash indeksów w manifeście),
GPR rolling refit z ledgerem. Wyniki powyżej – nie są dowodem przewagi; walk-forward na REAL_USER_DATA: **NOT_RUN** (brak danych z MT5 użytkownika w tym środowisku).

## 10. Testy integracyjne

| Polecenie (katalog `tests`) | Wynik |
|---|---|
| `python -m unittest test_mm_core` | 38 testów OK (matematyka, kontrakty, splity, Kalman, HDC, SMC bez lookahead, TSVP, BUZOA, GPR vs scipy, STFS/stack/STE, mathbench) |
| `python -m unittest test_mm_integration` | 17 testów: 15 OK + 2 pominięte w venv bota (OpenCL/ONNX – brak pakietów); w venv z pyopencl+pocl+onnx+onnxruntime oba OK |
| pełny zestaw `python -m unittest discover -p "test_*.py"` (73 pliki) | 811 testów: 807 OK, 2 pominięte (OpenCL/ONNX), 2 regresje wykryte i naprawione: wersja wiedzy agenta (test oczekiwał CTX na końcu łańcucha) oraz domyślne `--instrument XAUUSD` w `mm` CLI (reguła repo: instrument zawsze jawny) – moduły po poprawce ponownie: 56 testów OK |
| transliteracja MQL5 → Python (skrypty weryfikacyjne) | Breakout core 52 przebiegi / 0 różnic; Kalman 33 przebiegi / 0 różnic |

`test_mm_integration` obejmuje: pełny graf orchestratora (subprocess, eksport syntetyczny), anulowanie, uszkodzony snapshot (BLOCKED_DATA_QUALITY,
zależne BLOCKED_DEPENDENCY, niezależne dalej działają), niezmienność artefaktów (suma kontrolna, brak statusu LIVE, promocja tylko VALIDATED_SHADOW, rollback),
ledger (dedup, dojrzewanie raz), drift (tylko SCHEDULE_CANDIDATE), parytet natywny (NOT_EXECUTED / PASS / FAIL / niepoprawny plik), statyczną izolację
(brak wywołań zleceń w `mm/`, brak API handlu w MQL5, zbalansowane nawiasy), istnienie plików z inwentarza, okablowanie runnera i rejestru SH,
narzędzie agenta, endpointy API na prawdziwym procesie serwera (tryb nie zmienia się).

## 11. Znalezione i naprawione błędy

* Eksport syntetyczny z symbolem `XAUUSD` i zamkniętym rynkiem – użycie `XAUUSD-` i `MQ_FAKE_MARKET_ALWAYS_OPEN=1` w testach.
* Breakout: licznik kwalifikacji liczony z przyciętych stref zaniżał wynik → osobny licznik `n_qualified`.
* GPR: pokrycie 1σ 0.27 przez za wąską siatkę szumu → rozszerzona siatka (udokumentowana) → ~0.68.
* STE-FlowNet: kolizja nazw parametrów (`Wr1` GRU vs refinement) → `Rw1/Rb1/Rw2/Rb2`.
* Event engine: rozjazd online/offline 0.011 → skaler dzielił stałą cechę przez 1e-12 (wzmocnienie błędu zaokrągleń) → skala 1.0 dla cech stałych; Δ = 5e-15.
* OpenCL: wielokrotne pobieranie kernela → kernele cache’owane; tryb auto tylko GPU (POCL CPU wolniejszy od numpy).
* GPR job zapisywał artefakt przed testem → zapis po teście ze statusem końcowym.
* TSVP: przy budżecie wierszy mniejszym niż liczba kubełków pełne przerysowanie zaczynało od początku w każdym przebiegu → pełne przerysowanie oznacza
  wszystkie kubełki jako brudne i dalej idą przebiegi częściowe (Python i MQL5, test budżetu).
* Orchestrator raportował `FINISHED` mimo odrzuconego snapshotu → statusy BLOCKED_DATA_QUALITY / FINISHED_WITH_BLOCKED.
* `mm` CLI miało domyślny instrument `XAUUSD` (łamało regułę „instrument zawsze jawny”) → `--instrument` wymagany, wybór XAUUSD/BTC.
* Port MQL5 stref wybicia: pierwsza wersja agregowała strefę bez listy członków (nie dało się zastąpić mniej skrajnego swingu) → lista członków jak w referencji.

## 12. Bezpieczeństwo wykonania

* `ModelOutput.execution_allowed` musi być `False` (wyjątek przy próbie inaczej); każdy endpoint i odczyt live zwraca `execution_allowed: false`.
* Pakiet `mm/` nie importuje gatewaya, egzekucji ani ryzyka i nie wywołuje `order_send` (test statyczny). Pliki MQL5 nie używają OrderSend/CTrade/Position* zapisu
  (test statyczny); `PMW_AlignMean.mq5` tylko czyta equity i zysk pozycji.
* Rola w rejestrze SH: `OBSERVATION` → `INFO`/`NONE`; nigdy bramka, dowód ani prawdopodobieństwo zdarzenia strategii.
* Optymalizatory nie zapisują konfiguracji produkcyjnej (`applied_to_production: false`). Brak statusu/wskaźnika LIVE; wskaźnik SHADOW przesuwa tylko VALIDATED_SHADOW.
* Raport każdego przebiegu: `safety.orders_sent = 0`.

## 13. Znane ograniczenia

* Brak REAL_USER_DATA w tym środowisku – trening i walidacja rynkowa wyłącznie na danych syntetycznych.
* Brak MetaEditora/MT5 – żaden plik MQL5 nie był kompilowany ani uruchomiony; parytet natywny ma status `NATIVE_NOT_EXECUTED` do czasu uruchomienia
  `PMW_MM_SelfTest.mq5`. API ALGLIB (`CMatrixDouble.Resize/Set/Get`) i ONNX (`OnnxGetInputTypeInfo`) przyjęto wg dokumentacji MQL5 – do potwierdzenia przy kompilacji.
* OpenCL sprawdzony tylko na urządzeniu POCL CPU w osobnym venv; pyopencl/onnx/onnxruntime nie są w venv bota (tam testy pomijane, nie zaliczane).
* Event engine i STE-FlowNet na żywo używają adaptera BAR_CLOSE_EVENTS (zdarzenia z zamkniętych świec), bo archiwum ticków użytkownika nie było dostępne.
* Tick volume to proxy aktywności (VWAP, TSVP), nie wolumen transakcyjny.

## 14. Niedokończone

| Pozycja | Status | Bloker |
|---|---|---|
| SDOm, Quant Momentum, Renko, H&S (nowa wersja), Data Grabber, Chart Sync | BLOCKED | brak plików specyfikacji w XXX.rar |
| Kompilacja i uruchomienie MQL5 (MasterModels + MathFidelity) | BLOCKED | brak MetaEditora/terminala |
| Trening i walidacja na danych rynkowych | NOT_RUN | brak REAL_USER_DATA (uruchomić zadanie `master_models` u siebie) |
| VALIDATED_SHADOW dla HDC/event/STE/GPR | NOT_REACHED | bramki nie przechodzą na danych syntetycznych |
| Obserwacja SHADOW na rachunku użytkownika | NOT_RUN | wymaga uruchomienia bota z MT5 użytkownika |

## 15. Uruchamianie

```
# inwentarz i stan
python -m masterquo mm inventory --instrument XAUUSD
python -m masterquo mm status --instrument XAUUSD
# trening (dataset = katalog z `python -m masterquo training export ...`)
python -m masterquo mm train --dataset <dir> --instrument XAUUSD --out <run_dir> --profile standard
#   albo: launcher treningu → zadanie "master_models" (to samo polecenie w osobnym procesie, z anulowaniem)
# benchmarki i eksporty
python -m masterquo mm buzoa-bench
python -m masterquo mm mathbench-export --out <dir>      # → MQL5\Files\PMW_MathFidelity\
python -m masterquo mm export-fixtures --out <dir>       # → MQL5\Files\PMW_MM\ ; po PMW_MM_SelfTest:
python -m masterquo mm export-fixtures --out <dir> --parity <PMW_MM_NATIVE.txt>
# rollback wskaźnika SHADOW
python -m masterquo mm rollback --instrument XAUUSD --model <model_id>
# testy
cd tests && python -m unittest test_mm_core test_mm_integration
```

SHADOW na żywo: uruchom bota → panel Neural Cyberpunk → „12 Master Models” (albo `/api/v1/mm/live`). Instalacja MQL5: skopiuj `mql5/MasterModels/*`
i `mql5/MathFidelity/*` do odpowiednich folderów `MQL5\` i skompiluj w MetaEditorze (szczegóły: `mql5/MathFidelity/README.md`).

## 16. Decyzja

**CONDITIONAL GO — INTEGRATED, SOME MODEL/DATA VALIDATION REMAINS** – wyłącznie dla dalszej walidacji w trybie SHADOW.

Warunki przed jakimkolwiek dalszym krokiem: (1) przebieg `master_models` na REAL_USER_DATA z Twojego MT5 i przejście bramek walidacji per model,
(2) kompilacja i self-test parytetu MQL5 w terminalu (`NATIVE_PARITY_PASS`), (3) obserwacja SHADOW z dojrzałym ledgerem (GPR n ≥ 200).
To nie jest gotowość do pracy na realnym rachunku: żaden moduł nie ma udowodnionej przewagi, a decyzja o handlu wymaga osobnej walidacji i Twojej zgody.
