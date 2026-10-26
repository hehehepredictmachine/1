# COMPONENT_INVENTORY – PepeMarketWizard 1.18 (audyt architektury, 26.10.2026)

Każdy komponent: ścieżki, odpowiedzialność, wejście → wyjście, interfejs, status implementacji i **czy faktycznie wykonuje się w bocie**.

* **Status implementacji** (z przeglądu kodu): DZIAŁAJĄCY, CZĘŚCIOWY, NIEUŻYWANY, ZDUPLIKOWANY, USZKODZONY, NIEZWERYFIKOWANY.
  `DZIAŁAJĄCY (SHADOW)` = działa, ale z definicji nie wpływa na zlecenia.
* **Wywoływany** (z pomiaru `coverage`, metoda w `ARCHITECTURE.md` §1):
  * `TAK – pętla bota (x/y funkcji)` – ciała x z y funkcji wykonały się w 12-minutowej pętli bota bez panelu;
  * `NA ŻĄDANIE – panel/API` – wykonuje się dopiero, gdy panel lub API o to poprosi;
  * `NIE – tylko import` – załadowany, ale żadna funkcja nie wykonała się w pomiarze (może być pokryty testami, np. silnik ryzyka SH,
    do którego w 12 min nie doszedł żaden setup);
  * `NIE – poza procesem bota` – trening, CLI, testy albo proces potomny `.venv_candles` (coverage go nie mierzy).
* Pomiar był na symulatorze; ścieżki zależne od brokera (odrzucenia, częściowe wypełnienia) nie mogły się wykonać.

## 1. Komponenty

| Warstwa | Komponent | Pliki (`backend/`) | Odpowiedzialność | Wejście → wyjście | Interfejs | Status | Wywoływany | Ograniczenia / problemy |
|---|---|---|---|---|---|---|---|---|
| 1 DATA | **MT5Worker** | `mt5/worker.py` | jedyny kanał do terminala; Execution Lock na order_send | wywołania MT5 -> wyniki/ wyjątki | kolejka priorytetów w wątku | DZIAŁAJĄCY | TAK – pętla bota (9/11 funkcji) | testowany tylko na symulatorze (B-MT5) |
| 1 DATA | **MarketBridge** | `mt5/bridge.py`, `mt5/clock.py` | bufory 6+ TF, świeca otwarta osobno, zegar serwera->UTC, konto, deale, ticki | MT5 -> bars(tf, closed), quote_status, account_status, deals | metody + listenery zdarzeń | DZIAŁAJĄCY | TAK – pętla bota (52/67 funkcji) | jedna para symboli aktywna naraz (XAUUSD/BTC) |
| 1 DATA | **FakeMT5 (symulator)** | `mt5/fake.py` | symulowany terminal dla demo/testów | seed -> bary/ticki/konto | API zgodne z MetaTrader5 | DZIAŁAJĄCY | TAK – pętla bota (30/43 funkcji) | nie odtwarza zachowania brokera |
| 1 DATA | **Data quality / zegar PC** | `data/quality.py`, `data/pcclock.py` | jakość danych per TF, świeżość, offset zegara | bary -> dq (analysis_allowed, entries_allowed, reason_codes) | funkcje | DZIAŁAJĄCY | TAK – pętla bota (8/11 funkcji) | SH ma własną kontrolę jakości (sh/context.py) – druga implementacja |
| 1 DATA | **AssetRegistry** | `assets/registry.py`, `mq_instruments.py` | allowlista XAUUSD/BTC, mapowanie symbolu brokera, ścieżki per instrument | config -> aktywny instrument | klasa | DZIAŁAJĄCY | TAK – pętla bota (21/30 funkcji) | — |
| 1 DATA | **Eksport historii** | `forecast/export.py`, `training/cli.py` | eksport zamkniętych świec + metadane + sha256 | MT5 -> CSV + source_metadata.json | CLI `training export` | DZIAŁAJĄCY | NIE – poza procesem bota (trening/CLI/testy/proces potomny) | uruchamiany przez trening, nie przez bota |
| 1 DATA | **Feature engineering (wiele rejestrów)** | `lab/features.py`, `ml/features.py`, `mm/features.py`, `extind/features.py` | cechy modeli | bary -> wektory cech | funkcje per rodzina | ZDUPLIKOWANY | TAK – pętla bota (1/23 funkcji) | 4+ niezależne rejestry cech (FS-1.0.0, ML FeatureEngine, mm FEATURES, extind) – brak wspólnego schematu |
| 2 INTEL | **MarketRegimeEngine (S01–S12)** | `strategies/regime.py` | reżim per TF dla silnika ACTIVE | TFView -> state TREND_UP/RANGE/... | tf_regime() | DZIAŁAJĄCY | TAK – pętla bota (2/2 funkcji) | inna definicja niż reżim SH (market_v2) |
| 2 INTEL | **RegimeMachine v2 + IncRegime (SH)** | `lab/market_v2.py`, `sh/context.py` | reżim/MBA/SMMA/Z-score; przyrostowy reżim M5 dla SH | bary -> TREND/RANGE/TRANSITION/HIGH_VOL | klasy | DZIAŁAJĄCY | TAK – pętla bota (46/57 funkcji) | druga definicja reżimu w ścieżce decyzyjnej |
| 2 INTEL | **Struktura i formacje** | `analysis/structure_v2.py`, `analysis/chart_patterns.py`, `analysis/candles.py`, `analysis/sci2.py` … | BOS/CHoCH, formacje, świece, poziomy | bary -> zdarzenia struktury | funkcje | DZIAŁAJĄCY | TAK – pętla bota (46/62 funkcji) | — |
| 2 INTEL | **SMC / Pullback / VAMD / Fractal** | `lab/context_ind/smc.py`, `lab/context_ind/vamd.py`, `lab/context_ind/fractal.py`, `lab/context_ind/service.py` | SMC BoS/CHoCH/IDM, momentum VAMD, Katz FD | bary -> stany | serwis SI | DZIAŁAJĄCY | TAK – pętla bota (31/41 funkcji) | obserwacja (bez wpływu na S01–S12) |
| 2 INTEL | **Płynność: boksy sesji, heatmapa** | `analytics/session_engine.py`, `analytics/liquidity_context.py`, `analytics/liquidation/service.py`, `analytics/liquidation/provider.py` | boksy sesji, sweepy, strefy heatmapy | bary/zewn. źródło -> strefy | LiquidityService | DZIAŁAJĄCY | TAK – pętla bota (26/35 funkcji) | heatmapa zewnętrzna wymaga klucza; OBSERVE |
| 2 INTEL | **Zmienność / walls** | `engine/volzones.py`, `analytics/black76.py`, `analysis/walls.py`, `engine/walls_service.py` | HV, Black-76, IV walls, PDH/PDL | D1 -> poziomy | WallsService | DZIAŁAJĄCY | TAK – pętla bota (17/31 funkcji) | IV = HV bez łańcucha opcji |
| 2 INTEL | **Analytics BB/MA, FFT/EMD/VMD, Double Bottom** | `analytics/service.py`, `analytics/ta.py`, `analytics/signal.py`, `analytics/double_bottom.py` | analiza obserwacyjna | bary -> kontrakt mq-analytics | AnalyticsService | DZIAŁAJĄCY | TAK – pętla bota (47/54 funkcji) | OBSERVE |
| 2 INTEL | **Structure Intelligence** | `lab/si_service.py`, `lab/quotes.py`, `analysis/neutralization.py` | snapshot struktury MTF, kwotowania, neutralizacja | bridge -> si_snapshots | StructureIntelligenceService | DZIAŁAJĄCY | TAK – pętla bota (40/57 funkcji) | prognozy tylko z modelu SHADOW (brak artefaktu = brak %) |
| 2 INTEL | **News / kalendarz** | `news/service.py` | okna wydarzeń makro | źródło -> risk_level | NewsService | CZĘŚCIOWY | TAK – pętla bota (6/8 funkcji) | kalendarz częściowy; w demo wyłączony |
| 3 STRATEGY | **Strategie S01–S12 + rejestr** | `strategies/registry.py`, `strategies/base.py`, `strategies/common.py`, `strategies/indicators.py` … | generowanie setupów (pullback, wybicia, powrót do średniej, odwrócenia, walls) | MarketView -> Draft | scan() | DZIAŁAJĄCY | TAK – pętla bota (79/90 funkcji) | parametry robocze; validation_status FUNCTIONAL_ONLY_OOS_NOT_RUN |
| 3 STRATEGY | **SetupTracker + AutoSelector (router)** | `strategies/tracker.py`, `strategies/selector.py`, `engine/active.py` | wersje setupów, histereza, wybór strategii wg reżimu | kandydaci -> wybrany setup | ActiveEngine | DZIAŁAJĄCY | TAK – pętla bota (30/34 funkcji) | rank = 0.35·fit + 0.65·score – stałe heurystyczne wagi, bez wyników OOS |
| 3 STRATEGY | **SCALPING / HEDGING setup engine** | `sh/setup.py`, `sh/coordinator.py`, `sh/config.py` | setup M1 z checklistą, koordynacja strategii | snapshot SH -> READY/WAIT/NO_TRADE | SHService.cycle | DZIAŁAJĄCY | TAK – pętla bota (12/15 funkcji) | próg P(TP2) = stałe 0.55 gdy model READY; model nieprzetrenowany |
| 3 STRATEGY | **Scalp Range→Sweep→Retest (SHADOW)** | `scalp/strategy.py`, `scalp/service.py`, `scalp/replay.py` | maszyna stanów scalp, SHADOW | M1/M5 -> READY_SHADOW | ScalpService | DZIAŁAJĄCY (SHADOW) | TAK – pętla bota (53/81 funkcji) | pokrywa się z S07/S12 RANGE_RECLAIM i SH SCALPING (trzy implementacje wejścia po sweepie) |
| 3 STRATEGY | **Reguły master models (Multi-Indicator, SMC FVG)** | `mm/multi_indicator.py`, `mm/smc_fvg.py`, `mm/breakout_zones.py`, `mm/kalman.py` | reguły SHADOW | bary -> RULE_SIGNAL | MMService.live | DZIAŁAJĄCY (SHADOW) | NA ŻĄDANIE – panel/API (44/56 funkcji) | OBSERVATION |
| 3 STRATEGY | **BotSignalService + MarketScanner** | `markets/signals.py`, `markets/scanner.py`, `markets/analysis.py` | sygnały S01–S10 na innych rynkach, śledzenie wyniku | bary rynków -> signal_history | serwis + Telegram | DZIAŁAJĄCY | TAK – pętla bota (23/30 funkcji) | tylko informacja; nie handluje |
| 3 STRATEGY | **Profil ORIGINAL (M02/M07)** | `engine/legacy.py`, `engine/lifecycle.py` | port referencyjnego silnika | bary -> setup M07 | EngineService (profil ORIGINAL) | DZIAŁAJĄCY | TAK – pętla bota (17/23 funkcji) | alternatywa dla ACTIVE |
| 4 MODELS | **Rejestr modeli (sh/models.py)** | `sh/models.py` | role model×strategia, sondy statusu | artefakty/runtime -> macierz | matrix(rt, inst) | DZIAŁAJĄCY | TAK – pętla bota (5/5 funkcji) | obejmuje SCALPING/HEDGING; brak ról dla S01–S12 |
| 4 MODELS | **Legacy ML DT + XGBoost** | `ml/service.py`, `ml/models.py`, `ml/router.py`, `ml/registry.py` … | P(net R > 0) setupu S01–S12, bramka ASSIST | setup -> calibrated_probability | MLRouter.gate | DZIAŁAJĄCY (SHADOW domyślnie) | TAK – pętla bota (30/93 funkcji) | bramka promocji: Brier ≤ bazowy bez marginesu SE (jak F-19) |
| 4 MODELS | **sh_tp_model P(TP2 przed SL)** | `sh/tpmodel.py` | jedyne P dokładnie zdarzenia strategii SH | cechy setupu -> p | TM.predict | DZIAŁAJĄCY (NOT_TRAINED) | TAK – pętla bota (2/13 funkcji) | wymaga danych klienta (B-DATA) |
| 4 MODELS | **gold_candles / Scalp A-B (proces .venv_candles)** | `forecast/service.py`, `gold_candles_runtime/worker.py` | P(DOWN/FLAT/UP), P(TP1 przed SL) innych zdarzeń | bary -> prognozy SHADOW | osobny proces | DZIAŁAJĄCY (SHADOW) | TAK – pętla bota (13/25 funkcji) | inne zdarzenie niż strategie |
| 4 MODELS | **Lab LOGREG/TREE/MiniRocket/XGB/ResNet1D/SEW-SNN** | `lab/service.py`, `lab/protocol.py`, `lab/nets.py`, `lab/minirocket.py` | triple-barrier LONG score | cechy -> score (nieskalibrowany) | LabService | DZIAŁAJĄCY (SHADOW) | TAK – pętla bota (14/77 funkcji) | score bez kalibracji |
| 4 MODELS | **Neural Scalp (TCN) + ML scalp (XGB)** | `lab/nss.py`, `lab/nss_service.py`, `ml/scalp_task.py` | P(TP1/SL/TIMEOUT), E[net_R] kandydata scalp | kandydat -> predykcja | serwisy OBSERVE | DZIAŁAJĄCY (OBSERVE) | TAK – pętla bota (21/86 funkcji) | inne zdarzenie niż strategie |
| 4 MODELS | **SI / flow / context models** | `lab/structure_task.py`, `lab/flow_context/task.py`, `lab/context_ind/task.py` | P(DOWN/FLAT/UP) M1/M5 | cechy -> predykcje | trening + SI | CZĘŚCIOWY | TAK – pętla bota (7/75 funkcji) | flow reaction / context_move: trening bez inferencji na żywo (F-17) |
| 4 MODELS | **Master models HDC/GPR/event/STE** | `mm/service.py`, `mm/gpr.py`, `mm/hdc.py`, `mm/event_engine.py` … | obserwacja; GPR na żywo z ledgerem | bary -> GAUSSIAN_PREDICTIVE itd. | MMService | DZIAŁAJĄCY (SHADOW) | TAK – pętla bota (1/84 funkcji) | mm/drift.py nie jest nigdzie wywoływany (tylko testy) |
| 4 MODELS | **Agent Claude** | `agent/service.py`, `agent/tools.py` | ocena setupu, weto | kontekst -> BUY/SELL/WAIT/NO_TRADE | ClaudeAgent.gate_for | DZIAŁAJĄCY | TAK – pętla bota (17/45 funkcji) | bez klucza: VETO nie blokuje |
| 5 EVAL | **Drzewo decyzji S01–S12** | `engine/decision.py`, `engine/checklist.py`, `engine/signal_contract.py` | DATA→MARKET→STRATEGY→TRIGGER→RISK→AI→ML→PERMISSION | setup+ryzyko+bramki -> decision | build() | DZIAŁAJĄCY | TAK – pętla bota (10/11 funkcji) | brak P(TP przed SL) i EV w decyzji; tylko RR_NET |
| 5 EVAL | **Model kosztów (3 implementacje)** | `risk/costs.py`, `sh/units.py`, `scalp/replay.py` | prowizja z historii, poślizg, spread | deale/konfig -> koszt | funkcje | ZDUPLIKOWANY | TAK – pętla bota (4/26 funkcji) | osobne modele kosztów: legacy (slippage_stress_points), SH (slippage_usd), scalp (slippage_ticks) |
| 5 EVAL | **Ocena setupów (nowa, SHADOW)** | `evaluation/contract.py`, `evaluation/engine.py`, `evaluation/outcome.py`, `evaluation/service.py` | wspólny kontrakt kandydata i oceny; P nazwanego zdarzenia, EV netto, p*, przedział Wilsona; ledger z dojrzewaniem wyniku z M1 | setupy S01–S12 (CONFIRMED), SH (READY) i scalp SHADOW (każdy kandydat z ceną wejścia) -> SetupAssessment + wynik | słuchacze ActiveEngine, SHService i ScalpService; reżim obu definicji (O4); licznik gotowości ASSIST (O2), `/api/v1/eval/*` | DZIAŁAJĄCY (SHADOW) | dodany po pomiarze; runtime demo 4 min: 96 wywołań słuchacza ścieżki A, 5 cykli SH, 2 oceny S06 (DEFER – brak modelu zdarzenia) | nie wpływa na decyzję (decyzja O2); S01–S12 bez modelu zdarzenia TP-przed-SL |
| 6 RISK | **Łączna ekspozycja (nowa, tylko odczyt)** | `evaluation/exposure.py` | pozycje obu ścieżek na symbol: FLAT / SINGLE_ENGINE / STACKING / CONFLICT | managed_positions + sh_plans -> status | `/api/v1/eval/exposure`, ocena setupu | DZIAŁAJĄCY (SHADOW) | TAK – przy każdej ocenie setupu (jw.) | tylko informacja – podwójnym wejściom zapobiega ścieżka główna (O1); bez pozycji ręcznych z terminala |
| 6 RISK | **Risk engine M11 (S01–S12)** | `risk/engine.py` | wielkość pozycji, RR_NET, limity, depozyt, ekspozycja | poziomy+konto -> PASS/CONDITIONAL/BLOCKED | evaluate() | DZIAŁAJĄCY | TAK – pętla bota (4/9 funkcji) | nie widzi planów SH w PAPER; limity domyślnie nieustawione |
| 6 RISK | **Risk engine SH** | `sh/risk.py`, `sh/hedge_fsm.py`, `sh/lifecycle.py` | sizing, limity SH, koszyk hedge | setup+konto -> PASS/BLOCK | RK.evaluate | DZIAŁAJĄCY | NIE – tylko import | liczy tylko plany SH; w PAPER nie widzi pozycji S01–S12; 1.20: HEDGING na NETTING jako REDUCE po walidacji replay (O3) |
| 6 RISK | **HedgeController (scalp, SHADOW)** | `scalp/hedge.py` | HOLD/REDUCE/CLOSE/HEDGE_PARTIAL | pozycja bazowa -> akcja | klasa | NIEUŻYWANY w decyzji | TAK – pętla bota (2/8 funkcji) | F-16: wywoływany z adverse_signal=None; zastąpiony automatem HEDGING |
| 6 RISK | **ModeManager / Execution Lock / STOP** | `execution/modes.py`, `config.py` | tryby SIGNALS/PAPER/AUTO_DEMO/AUTO_LIVE, STOP, wiązanie rachunku | config+konto -> gate | gate() | DZIAŁAJĄCY | TAK – pętla bota (25/33 funkcji) | AR-01: SH ignorował STOP (naprawione); 1.20: ścieżka główna per instrument – druga ścieżka tylko analizuje (O1) |
| 7 EXEC | **ExecutionGateway + PaperBroker** | `execution/gateway.py`, `execution/paper.py`, `execution/policy.py` | wysyłka zleceń S01–S12, PAPER | decyzja -> zlecenie/trade | execute() | DZIAŁAJĄCY | TAK – pętla bota (3/29 funkcji) | — |
| 7 EXEC | **PositionManager** | `execution/manager.py` | partiale, BE, rekonsyliacja S01–S12 | pozycje -> akcje | wątek | DZIAŁAJĄCY | TAK – pętla bota (9/30 funkcji) | — |
| 7 EXEC | **SHExecutor + SHStore** | `sh/executor.py`, `sh/store.py`, `sh/service.py` | wykonanie i stan planów SH | plan -> akcje (idempotentne) | SHService | DZIAŁAJĄCY | TAK – pętla bota (23/76 funkcji) | druga ścieżka wykonania obok gateway |
| 7 EXEC | **ManualPad** | `execution/manual.py` | ręczne zlecenia użytkownika | API -> zlecenie | API | DZIAŁAJĄCY | TAK – pętla bota (1/23 funkcji) | — |
| 8 LEARN | **Dziennik i statystyki** | `stats.py`, `engine/signal_view.py` | win rate, PF, R, ROI (Dietz), equity | trades/deale -> statystyki | API /stats | DZIAŁAJĄCY | TAK – pętla bota (3/12 funkcji) | `bot` z `trades` (bez zmian); nowe pole `engines`: per silnik i łącznie z `sh_plans` (AR-04); SH bez swapu |
| 8 LEARN | **Ledgery predykcji (wiele)** | `mm/ledger.py`, `forecast/service.py`, `lab/service.py` | zapis predykcji i dojrzewanie etykiet | predykcje -> wyniki | per rodzina | ZDUPLIKOWANY | TAK – pętla bota (23/39 funkcji) | >8 tabel/ledgerów predykcji z własną logiką dojrzewania |
| 8 LEARN | **Runner treningu + walidacja** | `training/runner.py`, `training/panel.py`, `sh/replay.py`, `sh/train_cli.py` | plan, 17 zadań, replay SH, walk-forward | eksport -> artefakty + raporty | CLI/proces | DZIAŁAJĄCY | NA ŻĄDANIE – panel/API (5/73 funkcji) | trening rynkowy NOT_RUN (B-DATA) |
| 8 LEARN | **Drift / retrain triggers** | `mm/drift.py` | PSI, residual, coverage | cechy -> SCHEDULE_CANDIDATE | funkcja | NIEUŻYWANY | NIE – poza procesem bota (trening/CLI/testy/proces potomny) | brak wywołania w runtime (tylko testy) |
| UI | **API FastAPI + WS** | `api/app.py` | 241 endpointów REST + WS | HTTP -> runtime | REST/WS | DZIAŁAJĄCY | TAK – pętla bota (4/261 funkcji) | jeden plik 2300+ linii |
Ścieżki skrócone: `masterquo/` pominięto; `…` = komponent ma więcej plików niż wypisane.

## 2. Rejestr modeli (żywy rejestr `backend/masterquo/sh/models.py`)

Status z sondy `probe()` w środowisku audytu (bez artefaktów i bez runtime). U klienta zależy od katalogu `data/`.
Role dotyczą strategii SCALPING i HEDGING; silnik S01–S12 używa wyłącznie legacy ML (ASSIST) i agenta (VETO) – zob. AR-03.

| id | rodzaj | grupa korelacji | rola w SH | wyjście (zdarzenie) | zadanie treningu | status |
|---|---|---|---|---|---|---|
| `data_quality` | DETERMINISTIC | DATA | DATA_QUALITY | OK/BLOCK + wiek danych | — | DATA_MISSING |
| `risk_engine` | DETERMINISTIC | RISK | RISK_ANOMALY | PASS/BLOCK + powody | — | DETERMINISTIC_OK |
| `news` | DETERMINISTIC | RISK | RISK_ANOMALY | blackout tak/nie | — | DETERMINISTIC_OK |
| `regime_v2` | DETERMINISTIC | REGIME | REGIME | TREND/RANGE/TRANSITION/HIGH_VOL | — | DETERMINISTIC_OK |
| `structure_v2` | DETERMINISTIC | STRUCTURE | DIRECTION_STRUCTURE | trend per TF | — | DETERMINISTIC_OK |
| `smc_pullback` | DETERMINISTIC | STRUCTURE | DIRECTION_STRUCTURE | trend SMC, aktywne poziomy | — | DETERMINISTIC_OK |
| `vamd` | DETERMINISTIC | MOMENTUM | TIMING | y (znak = momentum) | — | DETERMINISTIC_OK |
| `fractal` | DETERMINISTIC | REGIME | REGIME | TREND/NEUTRAL/CHOP | — | DETERMINISTIC_OK |
| `atr_vol` | DETERMINISTIC | VOLATILITY | VOLATILITY | ATR w USD | — | DETERMINISTIC_OK |
| `candles_patterns` | DETERMINISTIC | PATTERN | PATTERN | rola świecy / formacja | — | DETERMINISTIC_OK |
| `liquidity` | DETERMINISTIC | LIQUIDITY | LIQUIDITY | poziomy płynności | — | DETERMINISTIC_OK |
| `flow_sr` | DETERMINISTIC | STRUCTURE | DIRECTION_STRUCTURE/LIQUIDITY | kolor HA, pasma S/R | — | DETERMINISTIC_OK |
| `decomposition` | DETERMINISTIC | CYCLE | SUPERVISION | cykl dominujący (obserwacja) | — | DETERMINISTIC_OK |
| `sh_tp_model` | TRAINED | TP_EVENT_SH | TARGET_PROB | skalibrowane P dokładnie zdarzenia strategii | sh_models | NOT_TRAINED |
| `scalp_A` | TRAINED | M1_DIRECTION | DIRECTION_STRUCTURE/TIMING | P(DOWN/FLAT/UP) po kosztach | scalp_A | NOT_TRAINED |
| `scalp_B` | TRAINED | TP_OTHER_EVENT | SUPERVISION | P(TP1 przed SL) INNEGO setupu (score) | scalp_A | NOT_TRAINED |
| `gold_forecast` | TRAINED | M5_DIRECTION | DIRECTION_STRUCTURE/TIMING | P(DOWN/FLAT/UP) zamknięcia | forecast | NOT_TRAINED |
| `legacy_ml` | TRAINED | TP_OTHER_EVENT | SUPERVISION | P(net R > 0) setupu S01–S12 | ml | UNAVAILABLE |
| `lab` | TRAINED | TP_OTHER_EVENT | SUPERVISION | score triple-barrier LONG (nieskalibrowany) | lab | NOT_TRAINED |
| `indicator_context` | TRAINED | TP_OTHER_EVENT | SUPERVISION | P(TP1 przed SL) polityki scalp (score) | indicator_context | NOT_TRAINED |
| `ml_scalp` | TRAINED | TP_OTHER_EVENT | SUPERVISION | P(net_R > 0), E[net_R] innego cyklu | ml_scalp | NOT_TRAINED |
| `nss` | TRAINED | TP_OTHER_EVENT | SUPERVISION | P(TP1_FIRST/SL_FIRST/TIMEOUT) innego setupu | neural_scalp | NOT_TRAINED |
| `si_move` | TRAINED | M1_DIRECTION | DIRECTION_STRUCTURE/TIMING | P(DOWN/FLAT/UP) + kwantyle r_h/ATR | structure_intelligence | NOT_TRAINED |
| `flow_reaction` | TRAINED | M1_DIRECTION | TIMING | P(DOWN/FLAT/UP) M1; stany Markowa | flow_context | NOT_TRAINED |
| `context_move` | TRAINED | M5_DIRECTION | DIRECTION_STRUCTURE/TIMING | P(DOWN/FLAT/UP) M5 | context_indicators | NOT_CONNECTED |
| `mm_align_mean` | DETERMINISTIC | MM_MEAN_REF | OBSERVATION | odległość od średniej (kontekst) | — | DETERMINISTIC_OK |
| `mm_kalman` | DETERMINISTIC | MM_TREND_FILTER | OBSERVATION | stan przecięcia + K | — | DETERMINISTIC_OK |
| `mm_breakout` | DETERMINISTIC | MM_ZONES | OBSERVATION | kierunek ostatniego wybicia, strefy | — | DETERMINISTIC_OK |
| `mm_multi_indicator` | DETERMINISTIC | MM_RULES | OBSERVATION | decyzja z pełnym śladem reguł | — | DETERMINISTIC_OK |
| `mm_smc_fvg` | DETERMINISTIC | STRUCTURE | OBSERVATION | setup entry/SL/2R (obserwacja) | — | DETERMINISTIC_OK |
| `mm_gpr` | TRAINED | MM_RETURN_DIST | OBSERVATION | N(mean, observed var) log-zwrotu 3 świec M5 | master_models | SHADOW_ONLY |
| `mm_hdc` | TRAINED | M5_DIRECTION | OBSERVATION | klasa + margines (nie prawdopodobieństwo) | master_models | NOT_TRAINED |
| `mm_event_engine` | TRAINED | EVENT_DIRECTION | OBSERVATION | P(DOWN/FLAT/UP) jednostki zdarzeń | master_models | NOT_TRAINED |
| `mm_ste_flownet` | TRAINED | EVENT_DIRECTION | OBSERVATION | prognoza log-zwrotu | master_models | NOT_TRAINED |
| `agent` | EXTERNAL | AGENT | SUPERVISION | BUY/SELL/WAIT/NO_TRADE bez prawdopodobieństwa | — | SHADOW_ONLY |

**Grupa korelacji = jeden dowód.** Modele z tej samej grupy (np. `M1_DIRECTION`: scalp_A, si_move, flow_reaction) liczą z tego samego
feedu cen; ich zgodność nie jest niezależnym potwierdzeniem.

**Prawdopodobieństwo vs score.** Prawdopodobieństwo zdarzenia strategii daje tylko `sh_tp_model` (TP2 przed SL dla SH) oraz legacy ML
(net R > 0 dla S01–S12 – inne zdarzenie niż TP przed SL). Pozostałe modele przewidują inne zdarzenia i są pokazywane jako score
z nazwą zdarzenia.

## 3. Tabele danych (65) – kto pisze, kto czyta

| Grupa | Tabele | Zapis | Odczyt |
|---|---|---|---|
| decyzje S01–S12 | `decisions`, `setups`, `strategy_setups`, `strategy_selection_log`, `signal_history` | EngineService, ActiveEngine, BotSignalService | API, panel, agent |
| wykonanie S01–S12 | `order_attempts`, `managed_positions`, `trades`, `paper_account`, `equity_snapshots` | gateway, PositionManager, PaperBroker | stats, ryzyko, panel |
| SH | `sh_signals`, `sh_plans`, `sh_events`, `sh_actions`, `sh_owners` | SHService | API SH (stats ich nie czytają – AR-04) |
| ledgery predykcji | `predictions`, `ml_predictions`, `ml_scalp_predictions`, `forecast_shadow`, `scalp_shadow`, `lab_forecasts`, `si_forecasts`, `quote_forecasts`, `nss_inferences`, `eval_ledger` + `data/mm/*/ledger.sqlite` | każdy serwis osobno | każdy serwis osobno (AR-10) |
| ML / lab | `ml_samples`, `ml_models`, `ml_jobs`, `ml_events`, `ml_scalp_samples`, `lab_trials`, `lab_holdout_access`, `lab_*` | trening, serwisy | trening, API |
| analiza | `analysis_snapshots`, `analytics_snapshots`, `si_snapshots`, `si_outcomes`, `mtf_snapshots`, `pattern_*`, `walls_snapshots`, `iv_observations`, `liq_*`, `extind_snapshots`, `neutraliz*` | serwisy analizy | panel, agent |
| system | `app_events`, `settings_audit`, `schema_migrations`, `clock_offsets`, `accounts_seen`, `account_prefs`, `agent_runs`, `agent_memory`, `ai_signals`, `notifications_sent`, `manual_*` | różne | różne |
