# 1.28 – Strefy rynkowe M1/M5/M15/M30, rejestr modeli i pipeline MT5 → trening → bot

Zakres: polecenie z 1.28 (strefy na M1/M5/M15/M30 z przyciskiem w panelu; audyt i spójna integracja modeli; pełny pipeline eksport MT5 →
przetwarzanie → trening → walidacja → zapis → ładowanie do bota). Punkt wyjścia: commit `32d8d7d` (1.27.0).

Środowisko prac: Linux, **symulator terminala (FakeMT5)**, bez Windows i bez zalogowanego MT5. Wszystko, co niżej oznaczono jako
sprawdzone, zostało uruchomione na symulatorze albo na danych syntetycznych. **Na danych rzeczywistych nie sprawdzono niczego**, a żaden
model nie był trenowany na Twojej historii (§9).

## 0. Najważniejsze w skrócie

| Obszar | Co jest w 1.28 | Gdzie |
|---|---|---|
| Strefy rynkowe | silnik PMW-MZ-1 dla M1/M5/M15/M30: S/R ze swingów, popyt/podaż, FVG, order blocks (z jawną regułą BOS), równe szczyty/dołki, konfluencja; pełny cykl życia stref, historia, odporność na rozłączenia | `zones/market.py`, `zones/market_service.py`, panel **Wykresy → Strefy rynkowe** |
| Eksport MT5 | historyczny i przyrostowy, partiami, z ponawianiem i wznawianiem, deduplikacja po (instrument, TF, czas), UTC, Parquet + CSV + manifest z sumami SHA-256, raport luk (sesja ≠ brak danych) | `marketdata/` |
| Pipeline | wspólne cechy dla treningu i inferencji, etykiety z kosztami, walk-forward z purgingiem i embargo, nietknięty zbiór końcowy, kalibracja, model bazowy, ocena po kosztach, paczki modeli, ręczna aktywacja z testem, rollback | `trainhub/` |
| Centrum treningu | kolejka zadań (trening w osobnym procesie), postęp, logi, czas, anulowanie, porównanie wersji, eksport datasetu i paczki, aktywacja i rollback | panel **Modele i trening → Centrum treningu**, `32_CENTRUM_TRENINGU.bat` |
| Modele | wspólny kontrakt predykcji PMW-PRED-1, rejestr 54 modułów z kategorią i stanem na żywo, reguły routingu i agregacji bez podwójnego liczenia | `modelhub/` |

Execution Lock: wycofany w 1.24 Twoją decyzją i **nie został przywrócony** ani zastąpiony ukrytą blokadą. Bez zmian pozostają:
- tryby SIGNALS / PAPER / AUTO DEMO / AUTO LIVE;
- przycisk STOP nowych wejść;
- limity ryzyka;
- licencje 1.27;
- wymagania brokera.

Nowe moduły nie mają ścieżki do zleceń ani do zapisu ustawień; sprawdza to test `TestIsolationFromTrading`, a dla przycisku stref test UI.

## 1. Audyt (etap 0)

Przepływ, który sprawdzono:
1. MT5 i bridge (`mt5/bridge.py`, wątek workera, czas serwera → UTC).
2. Dane: bufory bota, `symbol_bars`, eksporty `forecast/export.py`.
3. Cechy: osobne w każdej rodzinie modeli.
4. Modele: około 40 rodzin z osobnymi rejestrami.
5. Agregacja: `sh/models.py` (role i grupy korelacji), `mm/fusion.py`.
6. Strategie: S01–S12, SCALPING/HEDGING, R→S→R, Double Retest.
7. Panel.
8. Ryzyko i wykonanie: gateway, ManualPad, SHExecutor, STOP, licencja.

| # | Ustalenie | Skutek | Co zrobiono |
|---|---|---|---|
| A1 | Importy: wszystkie 218 modułów `masterquo` importują się bez błędu; brak zaślepek i TODO (poza abstrakcyjną metodą bazową strategii) | – | sprawdzono skryptem, bez zmian |
| A2 | Strefy istniały tylko na M5/M15 (HLZE+DSVIE+UZICE), dla aktywnego instrumentu, bez FVG i order blocków, bez przycisku i bez wyboru interwałów | brak wymaganego zakresu | nowy silnik PMW-MZ-1 obok HLZE (HLZE dalej zasila strategie – bez zmiany zachowania) |
| A3 | Eksport do treningu: CSV, wznawianie w obrębie folderu jednego eksportu, brak trwałego magazynu przyrostowego, brak Parquet, klasy luk tylko z heurystyki godzinowej, brak wersji schematu | dane z kolejnych eksportów nie łączą się; brak kontroli duplikatów między eksportami | `marketdata/`: magazyn z deduplikacją, manifest z sumami, klasy luk uczone z danych; stary eksport zostaje (używają go istniejące runy) |
| A4 | Brak wspólnego kontraktu predykcji – każda rodzina ma własny format i rejestr; stany „nie wytrenowany” / „błąd” nie były porównywalne między modelami | ryzyko, że błąd wygląda jak brak sygnału | `modelhub/contract.py` (stan + powód zamiast wartości), katalog z sondami na żywo |
| A5 | Wspólny runner treningu (W4) uruchamia wiele zadań z launcherów; brak w panelu kolejki z anulowaniem pojedynczego zadania, porównania wersji i aktywacji z testem predykcji | – | Centrum treningu (nowe zadania), runner W4 bez zmian |
| A6 | Czas historii: bridge zna tylko bieżący offset serwera; historia przez bridge bez modelu DST dałaby przesunięte świece przy zmianie czasu | błędne znaczniki czasu w datasecie | eksport przez bridge używa tego samego modelu DST co eksport standalone (`dst_model_probe`, `server_to_utc`), zamrożonego na cały przebieg |
| A7 | **Błąd znaleziony testem:** źródło danych przez bridge odczytywało flagę symulatora jako metodę (to właściwość) → wyjątek połykany → dane z symulatora oznaczone jako `REAL_USER_DATA` | syntetyczne dane wyglądałyby na rzeczywiste | naprawione: rozpoznanie przez moduł terminala; gdy nie da się ustalić – `UNKNOWN_SOURCE`, nigdy „rzeczywiste” |
| A8 | **Ryzyko podwójnego liczenia:** prognoza świec gold_candles (M5) i modele Centrum treningu M5 przewidują ten sam ruch | jeden sygnał liczony kilka razy | jedna grupa korelacji = jeden „mówca”; pozostałe tylko wymienione, bez uśredniania |
| A9 | Skew trening/inferencja: istniejące rodziny mają własne kontrole parity (lab, gold_candles); nowy pipeline używa JEDNEJ funkcji cech dla obu ścieżek | – | test: zmiana świec po chwili T nie zmienia cech do T; wyższy TF dołączany od zamknięcia |
| A10 | Wyścigi i duplikaty zadań: wielokrotny klik / równoległe przeliczenia / starszy wynik nadpisujący nowszy | migotanie, nieaktualne strefy | strefy: deduplikacja zadań, kolejność wg czasu danych i numeru zadania; trening: deduplikacja identycznych zadań, jedno zadanie naraz |
| A11 | Blokowanie panelu przez trening | panel „zamarza” | trening w osobnym procesie (niższy priorytet, limity wątków, na Windows limit pamięci Job Object) |

## 2. Rejestr modeli i modułów

W panelu tabela działa na żywo (Centrum treningu, sekcja 6) i pod API `GET /api/v1/models/catalog?instrument=XAUUSD|BTC`.
Źródła tabeli to:
- `sh/models.REGISTRY` (role w strategiach i sondy stanu);
- `mm/inventory.MODULES`;
- rejestr Centrum treningu;
- moduły 1.28.

Model opisany w dokumentacji, który nie ma kodu, występuje w tabeli z blokadą (np. `BLOCKED: SPEC_FILE_NOT_PROVIDED`). Nie jest przedstawiany jako zaimplementowany.

Kategorie:
- **trenowalny**: powstaje artefakt z treningu;
- **estymowany online / filtr**;
- **wskaźnik / obliczenie**;
- **reguła / bramka**;
- **symulacja**: Monte Carlo;
- **zewnętrzny**: agent Claude;
- **infrastruktura**: optymalizator, benchmark, dane.

Stany (sonda na żywo):
- **gotowy**;
- **niewytrenowany**;
- **trening**;
- **błąd**;
- **niezgodny**;
- **wyłączony**.

Stan „gotowy” dla modelu SHADOW oznacza gotowość do obserwacji, a nie dopuszczenie do głosu w strategii.

Schematy wejścia i wyjścia:
- dla modeli Centrum treningu: wejście `feature_schema.json` / `feature_order.json` w paczce, wyjście PMW-PRED-1;
- dla pozostałych rodzin: ich dotychczasowe kontrakty (kolumny „Wynik / cel” i „Wymagane dane”).

Tabela wygenerowana z kodu (stan statyczny – bez działającego bota):

| # | Moduł (id) | Kategoria | Lokalizacja | Wynik / cel | Wymagane dane | Trening | Instrumenty |
|---|---|---|---|---|---|---|---|
| 1 | Jakość i świeżość danych (bridge, zegar, spread) (`data_quality`) | reguła / bramka | mt5/bridge.py, engine (M01) | OK/BLOCK + wiek danych | notowania + świece z MT5 | nie dotyczy | XAUUSD, BTC |
| 2 | Wspólny silnik ryzyka SH (limity, margin, spread, ekspozycja) (`risk_engine`) | reguła / bramka | sh/risk.py | PASS/BLOCK + powody | rachunek, pozycje, specyfikacja symbolu | nie dotyczy | XAUUSD, BTC |
| 3 | Kalendarz makro (blokada wysokiego wpływu) (`news`) | reguła / bramka | news/ | blackout tak/nie | kalendarz makro | nie dotyczy | XAUUSD, BTC |
| 4 | Reżim rynku MQ_REGIME_MULTI_V2 (market_v2) (`regime_v2`) | wskaźnik / obliczenie | lab/market_v2.py | TREND/RANGE/TRANSITION/HIGH_VOL | świece M1–H1 | nie dotyczy | XAUUSD, BTC |
| 5 | Struktura rynku structure_v2 (M5/M15/H1, BOS/CHoCH) (`structure_v2`) | wskaźnik / obliczenie | lab/structure_v2.py | trend per TF | świece M5/M15/H1 | nie dotyczy | XAUUSD, BTC |
| 6 | Pullback + SMC (BoS/CHoCH/IDM) – context_ind (`smc_pullback`) | wskaźnik / obliczenie | lab/context_ind/smc.py | trend SMC, aktywne poziomy | świece M5 | nie dotyczy | XAUUSD, BTC |
| 7 | VAMD momentum (`vamd`) | wskaźnik / obliczenie | extind/vamd.py | y (znak = momentum) | świece M1/M5 | nie dotyczy | XAUUSD, BTC |
| 8 | Bounded Katz FD (trend/chop bez kierunku) (`fractal`) | wskaźnik / obliczenie | extind/fractal.py | TREND/NEUTRAL/CHOP | świece M1/M5 | nie dotyczy | XAUUSD, BTC |
| 9 | Zmienność ATR(14) M1/M5 + StopDistance (`atr_vol`) | wskaźnik / obliczenie | strategies/indicators.py | ATR w USD | świece M1/M5 | nie dotyczy | XAUUSD, BTC |
| 10 | Świece i formacje (candles, chart_patterns, sci2) (`candles_patterns`) | wskaźnik / obliczenie | analysis/candles.py, analysis/chart_patterns.py | rola świecy / formacja | świece | nie dotyczy | XAUUSD, BTC |
| 11 | Płynność: sesje (sweep boxes) + heatmapa likwidacji (`liquidity`) | wskaźnik / obliczenie | analytics/liquidity_context.py, analytics/session_engine.py | poziomy płynności | świece M5, sesje | nie dotyczy | XAUUSD, BTC |
| 12 | Heikin Flow + kanały S/R (flow_context) (`flow_sr`) | wskaźnik / obliczenie | lab/flow_context/ | kolor HA, pasma S/R | świece M1/M5 | nie dotyczy | XAUUSD, BTC |
| 13 | Dekompozycja sygnału FFT/EMD/VMD (analytics) (`decomposition`) | wskaźnik / obliczenie | analytics/ (FFT/EMD/VMD) | cykl dominujący (obserwacja) | świece | nie dotyczy | XAUUSD, BTC |
| 14 | SH: P(TP2 przed SL w horyzoncie) – model zdarzenia strategii (`sh_tp_model`) | trenowalny | sh/tpmodel.py | skalibrowane P dokładnie zdarzenia strategii | historia klienta (cykle SH) + świece | sh_models | XAUUSD, BTC |
| 15 | Scalp A – kierunek 1/3/5 min (LR/HGB/MLP) (`scalp_A`) | trenowalny | scalp/ (runner scalp) | P(DOWN/FLAT/UP) po kosztach | eksport M1–H1 | scalp_A | XAUUSD, BTC |
| 16 | Scalp B – jakość setupu Range→Sweep→Retest (`scalp_B`) | trenowalny | scalp/ | P(TP1 przed SL) INNEGO setupu (score) | eksport M1–H1 + cykle R→S→R | scalp_A | XAUUSD, BTC |
| 17 | gold_candles – prognoza świec 5/15/30 min (`gold_forecast`) | trenowalny | forecast/ (gold_candles) | P(DOWN/FLAT/UP) zamknięcia | eksport M5/M30 | forecast | XAUUSD, BTC |
| 18 | Legacy ML Decision Tree + XGBoost (setupy S01–S12) (`legacy_ml`) | trenowalny | ml/ (DT + XGBoost) | P(net R > 0) setupu S01–S12 | historia setupów S01–S12 | ml | XAUUSD, BTC |
| 19 | Lab: LOGREG/TREE/MiniRocket/XGB/ResNet1D/SEW-SNN (`lab`) | trenowalny | lab/models (LOGREG/TREE/MiniRocket/XGB/ResNet1D/SEW-SNN) | score triple-barrier LONG (nieskalibrowany) | eksport + etykiety triple-barrier | lab | XAUUSD, BTC |
| 20 | Kontekst wskaźników SAR + IQ (reakcja) (`indicator_context`) | trenowalny | extind/ (SAR+IQ) | P(TP1 przed SL) polityki scalp (score) | eksport M1/M5 | indicator_context | XAUUSD, BTC |
| 21 | Scalp ML XGBoost (net R cyklu) (`ml_scalp`) | trenowalny | ml/scalp_task.py | P(net_R > 0), E[net_R] innego cyklu | eksport M1–M15 | ml_scalp | XAUUSD, BTC |
| 22 | Neural Scalp System (TCN) (`nss`) | trenowalny | scalp/nss (TCN) | P(TP1_FIRST/SL_FIRST/TIMEOUT) innego setupu | eksport M1 | neural_scalp | XAUUSD, BTC |
| 23 | Structure Intelligence – ruch M1 h=3/5/15 (ResNeXt/SEW/SpikingBrain/MiniRocket v2…) (`si_move`) | trenowalny | lab/structure_intelligence/ | P(DOWN/FLAT/UP) + kwantyle r_h/ATR | ticki/świece M1 | structure_intelligence | XAUUSD, BTC |
| 24 | Flow context – model reakcji M1 + Markov3 (`flow_reaction`) | trenowalny | lab/flow_context/markov.py | P(DOWN/FLAT/UP) M1; stany Markowa | świece M1 | flow_context | XAUUSD, BTC |
| 25 | Context indicators – CONTEXT_MOVE_M5_V1 (`context_move`) | trenowalny | lab/context_ind/ | P(DOWN/FLAT/UP) M5 | świece M5 | context_indicators | XAUUSD, BTC |
| 26 | Align Mean (wspólna średnia, odległość w ATR) (`mm_align_mean`) | wskaźnik / obliczenie | mm/align_mean.py | odległość od średniej (kontekst) | świece | nie dotyczy | XAUUSD, BTC |
| 27 | Kalman crossover fast/slow (zamknięte świece) (`mm_kalman`) | wskaźnik / obliczenie | mm/kalman.py | stan przecięcia + K | świece M5 | nie dotyczy | XAUUSD, BTC |
| 28 | Breakout zones + robust volatility (`mm_breakout`) | wskaźnik / obliczenie | mm/breakout_zones.py, mm/robust_vol.py | kierunek ostatniego wybicia, strefy | świece M5 | nie dotyczy | XAUUSD, BTC |
| 29 | Multi-Indicator Strategy (RSI/SAR/HA/Stoch/CCI/W%R/Power) (`mm_multi_indicator`) | wskaźnik / obliczenie | mm/multi_indicator.py | decyzja z pełnym śladem reguł | świece M5 | nie dotyczy | XAUUSD, BTC |
| 30 | SMC BoS/IDM/FVG continuation (głębokość cofnięcia 73% – parametr, nie skuteczność) (`mm_smc_fvg`) | wskaźnik / obliczenie | mm/smc_fvg.py | setup entry/SL/2R (obserwacja) | świece M5 | nie dotyczy | XAUUSD, BTC |
| 31 | GPR Matérn 3/2 – prognoza log-zwrotu z niepewnością (`mm_gpr`) | trenowalny | mm/gpr.py | N(mean, observed var) log-zwrotu 3 świec M5 | świece M5 | master_models | XAUUSD, BTC |
| 32 | HDC – hiperwektory binarne (DOWN/FLAT/UP) (`mm_hdc`) | trenowalny | mm/hdc.py | klasa + margines (nie prawdopodobieństwo) | cechy M5 | master_models | XAUUSD, BTC |
| 33 | Event engine GRU + state stack + korelacja (+STFS) (`mm_event_engine`) | trenowalny | mm/event_engine.py | P(DOWN/FLAT/UP) jednostki zdarzeń | ticki / zdarzenia | master_models | XAUUSD, BTC |
| 34 | STE-FlowNet (adaptacja finansowa) – log-zwrot h zdarzeń (`mm_ste_flownet`) | trenowalny | mm/ste_flownet.py | prognoza log-zwrotu | zdarzenia | master_models | XAUUSD, BTC |
| 35 | Centrum treningu: kierunek po kosztach (LOGREG/HGB/XGB, aktywne paczki) (`th_direction`) | trenowalny | trainhub/inference.py (aktywne paczki) | P(DOWN/FLAT/UP) w H świecach po kosztach (kalibracja dev) | świece M1–M30 przez bridge | trainhub | XAUUSD, BTC |
| 36 | Agent Claude (weto, opis) (`agent`) | zewnętrzny (Claude) | agent/ | BUY/SELL/WAIT/NO_TRADE bez prawdopodobieństwa | kontekst + klucz API | nie dotyczy | XAUUSD, BTC |
| 37 | BUZOA Optimization Engine (`mm_buzoa`) | optymalizator / benchmark / dane | backend/masterquo/mm/buzoa.py | OPTIMIZER_RESULT | objective adapter (train/val only) | NOT_APPLICABLE (optimiser) | XAUUSD, BTC |
| 38 | SDOm Optimization Engine (`mm_sdom`) | optymalizator / benchmark / dane | — | — | — | NOT_APPLICABLE | XAUUSD, BTC |
| 39 | S3CE-Net / STFS (training-time sampling) (`mm_stfs`) | trenowalny | backend/masterquo/mm/stfs.py | training views + losses (no inference output) | event-encoder feature map [B,T,C] | APPLICABLE (as a training strategy) | XAUUSD, BTC |
| 40 | Quant Ultimate Momentum Pro / Quant 2nd Model / Momentum AI Fusion (`mm_quant_momentum`) | trenowalny | — | — | — | UNKNOWN | XAUUSD, BTC |
| 41 | Renko Regression Forecasting (`mm_renko`) | trenowalny | — | — | — | UNKNOWN | XAUUSD, BTC |
| 42 | Head & Shoulders Structure Detector (`mm_head_shoulders`) | wskaźnik / obliczenie | backend/masterquo/analysis/chart_patterns.py (istniejący detektor formacji, w tym H&S) | — | — | NOT_APPLICABLE | XAUUSD, BTC |
| 43 | Multi-TF Data Grabber Lite (`mm_data_grabber`) | optymalizator / benchmark / dane | backend/masterquo/forecast/export.py (istniejący eksport historii zamkniętych świec + metadane + sha256) | — | — | NOT_APPLICABLE | XAUUSD, BTC |
| 44 | Confirmed Swing Breakout Zones + Robust Volatility (`mm_breakout_zones`) | wskaźnik / obliczenie | backend/masterquo/mm/breakout_zones.py, backend/masterquo/mm/robust_vol.py, mql5/MasterModels/Include/PMW/PMW_BreakoutCore.mqh, mql5/MasterModels/Indicators/PMW_BreakoutZones.mq5 | zones, breakout events, latest-direction panel; dispersion stats | closed OHLC + tick volume (VWAP proxy) | NOT_APPLICABLE | XAUUSD, BTC |
| 45 | Tick Session Volume Profile (`mm_tsvp`) | wskaźnik / obliczenie | backend/masterquo/mm/tsvp.py, mql5/MasterModels/Include/PMW/PMW_TSVPCore.mqh, mql5/MasterModels/Indicators/PMW_TickSessionVP.mq5 | buckets, POC, render state | MT5 ticks (proxy or actual trade volume) | NOT_APPLICABLE | XAUUSD, BTC |
| 46 | Math Engine Fidelity Benchmark (`mm_mathbench`) | optymalizator / benchmark / dane | backend/masterquo/mm/mathbench.py, mql5/MathFidelity/train_export_model.py, mql5/MathFidelity/Experts/MathFidelityBenchmark_EA.mq5, mql5/MathFidelity/Indicators/FidelityMonitor.mq5, mql5/MathFidelity/Scripts/MathFidelity_SelfTest.mq5 | BENCHMARK_RESULT | — | NOT_APPLICABLE | XAUUSD, BTC |
| 47 | MT5 Multi-Timeframe Chart Synchronization (`mm_chart_sync`) | wskaźnik / obliczenie | frontend (istniejąca opcjonalna synchronizacja wykresów w panelu, J1) | — | — | NOT_APPLICABLE | XAUUSD, BTC |
| 48 | Strefy rynkowe M1/M5/M15/M30 (PMW-MZ-1) (`market_zones`) | wskaźnik / obliczenie | zones/market.py, zones/market_service.py | strefy S/R, popyt/podaż, FVG, order blocks, EQH/EQL + konfluencja | zamknięte świece M1–M30 z MT5 | nie dotyczy | XAUUSD, BTC |
| 49 | Mapa stref HLZE+DSVIE+UZICE (M5/M15) (`zone_map`) | wskaźnik / obliczenie | zones/engine.py, zones/service.py | strefy + profile sesji dla strategii | świece M5/M15/H1/D1 | nie dotyczy | XAUUSD, BTC |
| 50 | Monte Carlo ścieżek cen (PMW-MC-1) (`monte_carlo`) | symulacja | montecarlo/ | P(TP przed SL w horyzoncie) – symulacja, nie model uczony | świece M1 | kalibracja: montecarlo validate | XAUUSD, BTC |
| 51 | Bazowy – częstości klas – kierunek po kosztach (Centrum treningu) (`th_baseline`) | trenowalny | trainhub/learn.py, trainhub/features.py | P(DOWN/FLAT/UP) ruchu po kosztach w horyzoncie H świec | magazyn świec data/marketdata (M1/M5/M15/M30, eksport z MT5) | Centrum treningu / trainhub | XAUUSD, BTC |
| 52 | Regresja logistyczna (wieloklasowa) – kierunek po kosztach (Centrum treningu) (`th_logreg`) | trenowalny | trainhub/learn.py, trainhub/features.py | P(DOWN/FLAT/UP) ruchu po kosztach w horyzoncie H świec | magazyn świec data/marketdata (M1/M5/M15/M30, eksport z MT5) | Centrum treningu / trainhub | XAUUSD, BTC |
| 53 | Gradient boosting (histogramowy) – kierunek po kosztach (Centrum treningu) (`th_hgb`) | trenowalny | trainhub/learn.py, trainhub/features.py | P(DOWN/FLAT/UP) ruchu po kosztach w horyzoncie H świec | magazyn świec data/marketdata (M1/M5/M15/M30, eksport z MT5) | Centrum treningu / trainhub | XAUUSD, BTC |
| 54 | XGBoost (CPU) – kierunek po kosztach (Centrum treningu) (`th_xgb`) | trenowalny | trainhub/learn.py, trainhub/features.py | P(DOWN/FLAT/UP) ruchu po kosztach w horyzoncie H świec | magazyn świec data/marketdata (M1/M5/M15/M30, eksport z MT5) | Centrum treningu / trainhub | XAUUSD, BTC |

Liczba wg kategorii: reguła / bramka 3, wskaźnik / obliczenie 21, trenowalny 24, zewnętrzny (Claude) 1, optymalizator / benchmark / dane 4, symulacja 1

## 3. Strefy rynkowe – jak używać

Panel: **Wykresy → Strefy rynkowe M1/M5/M15/M30** (`#/strefy`).

1. Wybierz instrument: **XAUUSD** (symbol brokera `XAUUSD-`) albo **BTC** (`BTCUSDT-` – ustaw mapowanie w Ustawieniach, jeśli puste).
2. Przyciskami **M1 / M5 / M15 / M30** wybierz interwały – domyślnie wszystkie cztery (co najmniej jeden zostaje zaznaczony).
3. **Wyznacz strefy teraz**:
   - pobiera zamknięte świece przez bridge, liczy strefy i rysuje je na wykresie każdego interwału;
   - pasek postępu pokazuje etap;
   - ponowne kliknięcie w trakcie zwraca to samo zadanie (bez duplikatu).
4. **Aktualizacja na żywo**:
   - każdy interwał jest przeliczany dopiero po zamknięciu SWOJEJ świecy (strefy M15 po zamknięciu M15);
   - między zamknięciami cena na żywo oznacza dotknięcia i przełamania jako **wstępne**;
   - jest jedna subskrypcja na instrument, więc ponowne włączenie nic nie dubluje.
5. **Zatrzymaj**: wyłącza aktualizację na żywo i anuluje zadania w kolejce. Narysowane strefy zostają.
6. Statusy źródła dla każdego interwału:
   - **połączone**;
   - **dane nieaktualne** (ostatnia zamknięta świeca starsza niż 3 świece – np. rynek zamknięty);
   - **brak danych**;
   - **błąd** (np. terminal rozłączony).
7. Panel pokazuje także czas ostatnich danych i ostatniego przeliczenia.
8. Po utracie danych ostatnie strefy zostają, ale są szare i oznaczone „nieaktualne”. Po ponownym połączeniu tryb na żywo sam przelicza.
9. Kliknięcie strefy (na wykresie albo na liście) otwiera szczegóły:
   - pola strefy, składniki jakości i historia zdarzeń;
   - **checklista** – opis strefy, nie sygnał wejścia.
10. Zmiana instrumentu nie pokazuje stref drugiego instrumentu: odpowiedzi dla poprzedniego wyboru są ignorowane, a wyniki trzymane osobno.

Przycisk i tryb na żywo **nie otwierają pozycji i nie zmieniają ustawień handlu**. Test UI porównuje konfigurację przed i po.

### Reguły (PMW-MZ-1)

Strefa jest wykrywalna dopiero od zamknięcia świecy, na której reguła mogła być oceniona (`detectable_from`). Wcześniej nie istnieje.

Reguły wykrywania:
- **S/R (swing)**:
  - potwierdzony pivot: `left` świec ≥, `right` świec ściśle; znany po zamknięciu świec potwierdzenia;
  - wielkość ≥ `prom_atr` × ATR14;
  - strefa od knota do korpusu, maks. 0,25 ATR;
  - kandydat bez pełnego potwierdzenia (≥ 1 świeca po nim) jest **wstępny**.
- **Popyt / podaż**: świeca bazowa (zakres ≤ 1,0 ATR), a w ≤ 3 świecach zamknięcie za ekstremum bazy o ≥ 1,5 ATR, przy korpusie impulsu ≥ 60% zakresu.
- **FVG**: `low[i] > high[i-2]` (wzrostowa) lub `high[i] < low[i-2]` (spadkowa), luka ≥ max(0,3 ATR, min. szerokość). Znana po zamknięciu świecy i.
- **Order block**:
  - warunek: zamknięcie za ostatnim swingiem, który był już **potwierdzony** przed tą świecą (BOS);
  - OB to ostatnia świeca przeciwnego koloru między swingiem a świecą BOS;
  - znany dopiero po zamknięciu świecy BOS; bez BOS nie ma OB.
- **EQH / EQL**:
  - ≥ 2 potwierdzone swingi w odległości ≤ `eq_tol_atr` × ATR i ≥ 3 świece od siebie, bez zamknięcia za poziomem pomiędzy;
  - opisane jako **potencjalna płynność wnioskowana z OHLC**, nie jako zmierzona płynność ani zlecenia oczekujące.

Cykl życia:
- stany: **wstępna → aktywna → testowana → unieważniona / wygasła**;
- **test**: świeca sięga strefy po ≥ `test_gap` świecach poza nią. Dotknięcia bez wyjścia ze strefy liczą się jako jeden test (liczone są niezależne testy);
- **unieważnienie**: zamknięcie za dalszą granicą o ≥ `break_atr` × ATR (sam knot nie unieważnia). EQH/EQL unieważnia już knot za poziomem;
- **wygaśnięcie**: więcej niż `max_age` świec (M1 720, M5 576, M15 480, M30 480).

Jakość 0–100:
- składniki: struktura 30, reakcja 25, świeżość 15, testy 10, konfluencja 15, szerokość 5;
- zwracana razem ze składnikami;
- to **nie jest prawdopodobieństwo**: pole `probability` = brak, kalibracja „brak”.

Łączenie i konfluencja:
- łączone są tylko strefy tego samego typu i interwału, nakładające się ≥ 50%, obie żywe;
- strefa łączona zachowuje id najstarszej, listę członków (pochodzenie) i `segments`;
- granice poszerzają się dopiero od chwili, gdy kolejny członek stał się znany (testy liczone granicami znanymi w danej chwili);
- różne interwały nigdy się nie łączą – zamiast tego jest **konfluencja**: nakładające się zakresy o zgodnym kierunku, tylko spośród stref znanych w danej chwili.

Skalowanie: parametry rosną z ATR14 danego interwału i z profilem instrumentu:
- **złoto**: min. szerokość 10 ticków / 0,3 bp / 2× spread, EQ 0,12 ATR, przełamanie 0,15 ATR;
- **BTC**: 100 ticków / 0,8 bp / 2× spread, EQ 0,18 ATR, przełamanie 0,25 ATR.

Widoczność i historia:
- widocznych jest najwyżej 8 stref na interwał (stan, jakość, odległość od ceny); pozostałe są w API (`?all=true`);
- historia (`data/zones/market_zones.sqlite`) zapisuje każde przeliczenie i zdarzenia stref bez duplikatów;
- stan „na chwilę” odtwarza `GET /api/v1/market-zones/as-of?as_of=...` (świece ucięte na tej chwili) albo zdarzenia strefy.

API stref:
- `GET /api/v1/market-zones`, `POST .../compute`, `POST .../live`, `POST .../stop`;
- `GET .../zone/{id}`, `GET .../events`, `GET .../bars`, `GET .../as-of`.

## 4. Eksport MT5 → trening → aktywacja

### Panel (Modele i trening → Centrum treningu, `#/trening`)

1. **Instrument**: XAUUSD albo BTC. Są trenowane i oceniane osobno.
2. **Eksportuj dane**:
   - tryb przyrostowy (od ostatniej zapisanej świecy) albo historyczny (od–do);
   - interwały M1/M5/M15/M30;
   - przy pierwszym eksporcie wybierz liczbę dni wstecz;
   - eksport idzie przez bridge bota (ten sam terminal, zapytania o niskim priorytecie).

   Tabela danych pokazuje:
   - liczbę świec, zakres i dni;
   - jakość;
   - luki: weekend / przerwa sesji / brak ticków / **BRAKI**;
   - koszty (co zmierzone, a co jest założeniem);
   - konwencję czasu serwera.
3. **Przygotuj dataset**: cechy + etykiety. **Eksportuj dataset (zip)** pobiera dataset z manifestem magazynu.
4. **Trenuj**:
   - wybierz modele (bazowy, regresja logistyczna, gradient boosting, XGBoost gdy dostępny), interwał bazowy, horyzont H, próg k×ATR i zakres dat;
   - trening działa w osobnym procesie;
   - panel, strefy i inferencja działają dalej;
   - **Anuluj** zatrzymuje proces.
5. **Uruchom cały proces**: eksport → walidacja danych → dataset → trening → ocena → paczki.
6. **Wersje**:
   - metryki ze zbioru końcowego obok modelu bazowego;
   - stabilność walk-forward;
   - ECE;
   - ocena po kosztach;
   - zaznacz 2 wersje, żeby je porównać.
7. **Oceń zaznaczoną wersję**: sprawdzenie na danych nowszych niż trening (po kolejnym eksporcie).
8. **Aktywuj**: działa tylko ręcznie i wymaga zaliczenia obu testów:
   - **test zgodności** – sumy SHA-256 paczki, instrument, wersja i hash schematu cech, kolejność cech, wersje sklearn/numpy (i xgboost);
   - **test predykcji** – wczytany model musi odtworzyć zapisane wyniki próbki.

   Przy niepowodzeniu: `INCOMPATIBLE` z listą powodów, a aktywna wersja zostaje bez zmian. Trening nigdy nie podmienia modelu sam.
9. **Rollback**: przywraca poprzednio aktywną wersję. **Wyłącz**: model bez aktywnej wersji. **Paczka**: zip wersji.

### Wiersz poleceń (folder `backend`, Python z `.venv`)

```
python -m masterquo trainhub export   --instrument XAUUSD                       # przyrostowo M1/M5/M15/M30 (własne połączenie z MT5)
python -m masterquo trainhub export   --instrument BTC --mode historical --from 2026-01-01 --to 2026-10-31
python -m masterquo trainhub import-data --instrument XAUUSD D:\kopia\marketdata\XAUUSD   # dane z innej maszyny (sumy sprawdzane)
python -m masterquo trainhub dataset  --instrument XAUUSD --base-tf M5 --horizon 6
python -m masterquo trainhub train    --instrument XAUUSD --models TH_BASELINE,TH_LOGREG,TH_HGB
python -m masterquo trainhub full     --instrument XAUUSD
python -m masterquo trainhub list     --instrument XAUUSD
python -m masterquo trainhub activate --instrument XAUUSD --model-key TH_LOGREG_M5_H6 --version <wersja>
python -m masterquo trainhub rollback --instrument XAUUSD --model-key TH_LOGREG_M5_H6
python -m masterquo trainhub evaluate --instrument XAUUSD --model-key TH_LOGREG_M5_H6 --version <wersja>
python -m masterquo trainhub package-zip --instrument XAUUSD --model-key TH_LOGREG_M5_H6 --version <wersja>
```
Kody wyjścia:
- 0 – ok;
- 1 – błąd;
- 2 – za mało danych albo zły argument;
- 3 – aktywacja odrzucona (niezgodność);
- 4 – MT5 niedostępny.

`--demo` uruchamia symulator: dane SYNTETYCZNE, tylko do sprawdzenia mechaniki.

Windows: **`32_CENTRUM_TRENINGU.bat`** – menu z pozycjami:
1. cały proces XAUUSD;
2. cały proces BTC;
3. tylko eksport;
4. lista wersji XAUUSD;
5. lista wersji BTC;
6. aktywacja.

### MT5 na innej maszynie

Program nie ma sieciowego dostępu do terminala na innym komputerze i tego nie deklaruje. Most działa przez pliki:
1. Na maszynie z MT5 uruchom eksport (panel tego bota albo `32_CENTRUM_TRENINGU.bat` → 3).
2. Skopiuj folder `data\marketdata\<INSTRUMENT>`.
3. Zaimportuj: `trainhub import-data`.

Import najpierw sprawdza sumy SHA-256 i wersję schematu z manifestu. Przy niezgodności niczego nie scala.

### Dane i koszty

- **Magazyn**: `data/marketdata/<INSTRUMENT>/<TF>/<RRRR-MM>.parquet` + `.csv` (te same wiersze).
  - Kolumny: czas UTC, OHLC wykresu brokera (MT5: zwykle Bid), tick volume (aktywność, nie wolumen transakcyjny), spread świecy w punktach, real volume (0 dla CFD), surowy czas serwera, flaga niejednoznaczności DST.
  - Klucz to (instrument, TF, czas). Ponowny eksport niczego nie dubluje.
  - Inne OHLC dla zapisanego czasu to konflikt: zostaje wiersz zapisany, konflikt jest wpisany do manifestu.
  - Błędna geometria OHLC jest odrzucana i listowana. Nic nie jest uzupełniane.
- **Tylko zamknięte świece**: granica to otwarcie świecy formującej się w chwili startu eksportu.
- **Luki** (`quality_report.json`):
  - weekend;
  - przerwa sesji (powtarzalna o tej samej godzinie UTC w ≥ 30% dni, ≤ 3 h – uczona z danych);
  - brak ticków (1–3 świece);
  - **BRAKI** (reszta, z liczbą brakujących świec);
  - rzeczywista dostępna historia dla każdego interwału.
- **Koszty**:
  - spread jest zmierzony dla każdej świecy (`MEASURED_PER_BAR` – nie jest historycznym bid/ask i nie jest rekonstruowany);
  - prowizja pochodzi wyłącznie z historii transakcji tego symbolu na rachunku (`DEALS_HISTORY`). Gdy jej brak: `UNKNOWN` i wtedy:
    - w etykietach używane jest założenie użytkownika (`commission_per_lot_per_side`), a w jego braku 0 z flagą `UNKNOWN_ZERO_USED` („zawyża ocenę”);
    - konto „Zero” nie oznacza zerowych kosztów;
  - poślizg to założenie stresowe (`slippage_stress_points`), oznaczone jako `ASSUMPTION_STRESS`.
- **Parquet** wymaga `pyarrow` – dodany do `requirements-win.txt` z hashami. Bez niego zapisywany jest sam CSV, a manifest to mówi.

### Pipeline i walidacja

- **Cechy PMW-TH-FEAT-1**: jedna funkcja dla treningu i bota. Wyższe interwały są dołączane tylko od zamknięcia ich świecy. Wiersz z brakami nie jest używany (trening go odrzuca, bot zgłasza błąd zamiast przewidywać).
- **Etykieta**: klasa DOWN/FLAT/UP zmiany zamknięcia za H świec względem progu max(k×ATR14, koszt świecy). Okno etykiety przez lukę sesji jest odrzucane.
- **Podział i walidacja**:
  - zbiór końcowy: ostatnie 20%, nietknięty do jednej oceny końcowej, oddzielony embargo H świec;
  - walk-forward z rosnącym oknem, 4 foldy, purging (etykieta treningu kończy się przed blokiem testu minus embargo);
  - na danych rozwojowych dobierane są: przetwarzanie (wewnątrz modelu), hiperparametry, temperatura kalibracji (out-of-fold), próg oceny handlowej i wagi agregacji (skill walk-forward). Zbiór końcowy nie jest do tego używany.
- **Metryki** (zbiór końcowy):
  - log loss, Brier, accuracy, balanced accuracy;
  - **skill względem modelu bazowego**;
  - ECE przed i po kalibracji z tabelą niezawodności;
  - stabilność: odchylenie foldów, liczba foldów lepszych od bazowego;
  - **ocena po kosztach** (sygnały, średni wynik netto w ATR, maks. obsunięcie) – osobno, bo trafność ≠ rentowność.
- **Minimum danych**: 2000 próbek z etykietą i ≥ 2 foldy po ≥ 500 próbek; zbiór końcowy ≥ 200. Inaczej pojawia się czytelny komunikat z liczbą dni do wyeksportowania.
- **Paczka**:
  - model.joblib (z przetwarzaniem), kolejność i schemat cech, konfiguracja, metryki;
  - manifest danych (pliki magazynu z SHA-256, hash datasetu, rodzaj danych, koszty);
  - wersje bibliotek, próbka inferencji, REPRODUCE.md, `package_manifest.json` (SHA-256 każdego pliku);
  - bez haseł, tokenów i kluczy (test).

## 5. Wspólny kontrakt predykcji i łączenie wyników

PMW-PRED-1 (`modelhub/contract.py`) zawiera:
- instrument, symbol i interwał;
- czas danych (zamknięcie ostatniej użytej świecy);
- nazwę i wersję modelu oraz wersję schematu cech;
- typ i nazwę zadania oraz horyzont;
- wynik i jednostkę;
- kalibrację (metoda i status);
- jakość i świeżość danych;
- czas obliczenia;
- stan i powód niedostępności.

Zasady:
- **Błąd nigdy nie wygląda jak wynik**: stan inny niż „gotowy” nie niesie wartości i musi mieć powód (walidator odrzuca naruszenie).
- **Kontrolowany fallback**: niezgodna paczka (schemat, biblioteka, suma), brak danych, dane nieaktualne albo niepełne cechy dają stan „niezgodny” lub „błąd” z powodem. Fallback to „brak głosu”, nigdy domyślne prawdopodobieństwo.
- **Mapowanie na strategie** jest jawne (`modelhub/aggregate.py` ROUTES):

  | Grupa | SCALPING | HEDGING |
  |---|---|---|
  | M1 | DIRECTION_STRUCTURE | TIMING |
  | M5 (także gold_candles) | TIMING | DIRECTION_STRUCTURE |
  | M15/M30 | DIRECTION_STRUCTURE | DIRECTION_STRUCTURE |

- **Podwójne liczenie**:
  - jedna grupa korelacji ma jednego mówcę (najlepszy skill walk-forward z danych rozwojowych);
  - pozostali członkowie są tylko wymienieni;
  - wyniki o różnych znaczeniach, horyzontach lub jednostkach nie są uśredniane.
- **Rola**: modele Centrum treningu i gold_candles są **OBSERVATION**. Nie głosują w SCALPING/HEDGING, dopóki nie zostaną zwalidowane w SHADOW na danych rzeczywistych. Bramki i system ryzyka bez zmian.
- **Adaptery**:
  - aktywne paczki Centrum treningu;
  - prognoza gold_candles (stany usługi zmapowane: NO_MODEL → niewytrenowany, CONTRACT_MISMATCH → niezgodny, STALE_DATA / NO_DATA → błąd itd.).
- **Pozostałe rodziny** (SH tp-model, scalp, legacy ML, lab, PMW-MM) publikują własne, inne zdarzenia przez swoje panele. W rejestrze mają wspólny stan, ale nie są przepisywane na kontrakt kierunku, bo przewidują inne zdarzenia.

API:
- `GET /api/v1/models/catalog`;
- `GET /api/v1/models/predictions`;
- `GET /api/v1/models/evidence?strategy=SCALPING|HEDGING`;
- `GET /api/v1/trainhub/...` (status, jobs, data, registry, version, package.zip, dataset.zip);
- `POST /api/v1/trainhub/jobs|activate|rollback|deactivate`.

## 6. Wykonane testy

Wszystkie testy uruchomiono w tym środowisku (Linux, Python 3.13, Chromium, **symulator terminala**). Wyniki dotyczą mechaniki kodu.
Żaden test nie mierzy jakości modeli ani trafności stref na rynku.

**Nowe testy 1.28:**

| Moduł | Testy | Wynik | Co sprawdza |
|---|---|---|---|
| `test_market_zones` | 19 | OK | potwierdzenie swingów / FVG / OB w czasie, EQH/EQL, testy / unieważnienie / wygaśnięcie, brak przyszłych danych (zmiana świec po T nie zmienia wyniku w T), świeca formująca się pominięta, odtworzenie stanu ze zdarzeń, 4 TF + konfluencja + limity, łączenie z pochodzeniem, profile złoto/BTC, brak importów ścieżki zleceń; serwis: wielokrotny klik, izolacja instrumentów, starszy wynik nie nadpisuje nowszego, utrata danych → nieaktualne → odzyskanie, live tylko po zamknięciu TF, jedna subskrypcja, odtworzenie po restarcie, zatrzymanie |
| `test_trainhub` | 22 | OK | eksport przyrostowy bez duplikatów, historyczny = same duplikaty, wznowienie po awarii, ponowienie, konflikt rewizji, klasy luk, import z sumami; cechy bez przyszłości, łączenie wyższego TF od zamknięcia, purging/embargo/holdout, koszty w etykietach; pipeline + każdy model, zapis/wczytanie = identyczne predykcje, blokada niezgodnych paczek, aktywacja i rollback, ocena bez nowych danych, BTC osobno; kolejka: proces osobny, deduplikacja, anulowanie, komunikat o braku danych, współbieżny dostęp do bazy zadań; kontrakt, agregacja (jeden głos na grupę), adapter gold_candles, brak ścieżki zleceń |
| `test_ui_market_zones` (Chromium) | 1 | OK | przycisk, podwójne kliknięcie = jedno zadanie, 4 wykresy ze strefami, pełny rekord strefy, szczegóły + checklista, przełączniki TF, zmiana na BTC, live + stop, konfiguracja i tryb bez zmian |
| `test_ui_training_center` (Chromium) | 1 | OK (2 kolejne przebiegi po poprawce) | eksport przez bridge, trening w osobnym procesie przy działającym panelu, anulowanie, aktywacja z testem, predykcja w kontrakcie, katalog, pobranie paczki, rollback, konfiguracja bez zmian |

**Regresja całego repozytorium** (każdy moduł osobno):
- **83 moduły nie-UI, 988 testów**;
- **14 modułów UI (Chromium), 92 testy**.

W pierwszym przebiegu 4 moduły miały po jednym niepowodzeniu. Każde wyjaśnione i poprawione, potem moduł uruchomiony ponownie w całości:

| Moduł | Przyczyna | Poprawka | Wynik po poprawce |
|---|---|---|---|
| `test_market_zones` | test live przesuwał zegar, zanim zadanie z poprzedniego odczytu skończyło pracę (zachowanie serwisu było poprawne) | test czeka na zakończenie zadania | 19/19, 4 przebiegi |
| `test_time_and_data` | reguła repozytorium „brak `default="XAUUSD"` w kodzie” złamana przez nowe CLI | `--instrument` wymagany | 16/16 |
| `test_structure_intelligence` | **istniejący wcześniej wyścig w teście**: status zadania zmienia się przed końcem wątku (eksport raportu) | pomocnik `wait` czeka też na koniec wątku | 21/21, 4 przebiegi |
| `test_ui_training_center` | **błąd w nowym kodzie**: wspólne połączenie SQLite kolejki zadań używane z dwóch wątków bez blokady (`InterfaceError`) | `SafeDB` – jedna blokada + test regresji | 1/1 w 2 przebiegach; `test_trainhub` 22/22 |

Dotychczasowe moduły ryzyka i wykonania przechodzą bez zmian:
- `test_risk_execution` 21;
- `test_execution_lock_withdrawn` 11;
- `test_license_client` 12;
- `test_sh_*` 77;
- `test_zones` 42;
- `test_launchers` 3 (nowy `.bat`: ASCII, CRLF, cudzysłowy).

**Dane syntetyczne a rzeczywiste**:
- wszystkie liczby metryk modeli z tych przebiegów pochodzą z symulatora (`SYNTHETIC_TEST`), łącznie z dodatnią „oceną po kosztach” niektórych modeli;
- nie są dowodem żadnej przewagi;
- testów na danych rzeczywistych nie było.

Weryfikacja zależności: `pip download --require-hashes` dla `pyarrow==26.0.0` (win_amd64, cp312 i cp313) przeszedł – hashe w `requirements-win.txt` są poprawne.

## 7. Wymagania 1–10 → dowód

| # | Wymaganie | Test |
|---|---|---|
| 1 | strefy M1/M5/M15/M30 wykrywane i rysowane | `test_market_zones` (wszystkie 4 TF, konfluencja, limity), `test_ui_market_zones` (4 wykresy z boxami, szczegóły) |
| 2 | aktualizacja po nowych świecach i unieważnienie | `test_live_recomputes_only_the_closed_timeframe…`, `test_independent_tests_invalidation_by_close_and_expiry` |
| 3 | brak danych z przyszłości (strefy i cechy) | `TestNoLookAhead`, `test_swing_known_only_after…`, `test_fvg…`, `test_order_block…`, `TestNoFutureData` |
| 4 | reconnect, dane nieaktualne, wielokrotny klik | `test_data_loss_keeps_zones_stale_and_recovers`, `test_button_all_four_tfs_multi_click…`, `test_older_result_never_overwrites_newer` |
| 5 | eksport przyrostowy bez duplikatów, wznawialny | `TestExport` (przyrostowy, historyczny = same duplikaty, wznowienie po awarii, ponowienie, konflikt rewizji, import z sumami) |
| 6 | pełny pipeline dla ≥ 1 modelu + adapter każdego modelu | `test_full_pipeline_and_every_adapter` (BASELINE/LOGREG/HGB/XGB), `test_ui_training_center` |
| 7 | zapis, wczytanie, równość predykcji | `test_save_load_same_predictions` (różnica 0,0) |
| 8 | blokada niezgodnych artefaktów | `test_incompatible_packages_are_blocked` (schemat, wersja sklearn, inferencja INCOMPATIBLE bez wartości) |
| 9 | panel działa podczas treningu, anulowanie, rollback | `TestJobsOutOfProcess`, `test_ui_training_center` (pid procesu treningu ≠ pid bota, nawigacja w trakcie, Anuluj, Rollback) |
| 10 | kontrola ryzyka i brak ukrytej blokady | `TestIsolationFromTrading`, `test_engine_has_no_trading_imports`, konfiguracja bez zmian w testach UI; regresja `test_risk_execution`, `test_execution_lock_withdrawn`, `test_license_client` |

## 8. Pliki

Nowe:
- `backend/masterquo/zones/market.py`, `zones/market_service.py`;
- `marketdata/{store,quality,sources,export}.py`;
- `trainhub/{features,dataset,learn,registry,pipeline,jobs,worker,inference,cli}.py`;
- `modelhub/{contract,catalog,aggregate,adapters}.py`;
- `frontend/src/features/market-zones/*`, `frontend/src/features/training-center/*`;
- `32_CENTRUM_TRENINGU.bat`;
- testy `test_market_zones.py`, `test_trainhub.py`, `test_ui_market_zones.py`, `test_ui_training_center.py`.

Zmienione:
- `runtime.py` (usługi), `api/app.py` (trasy), `__main__.py` (`trainhub`);
- `sh/models.py` (wpis `th_direction`, rola OBSERVATION);
- `router.ts` / `App.tsx` (2 strony);
- `requirements-win.txt` (pyarrow);
- `tools/model_map.py` + `MAPA_MODELI_I_TRENINGU.*`;
- wersja 1.28.0.

## 9. Czego nie zweryfikowano / blokery

- **Brak MT5 i Windows w środowisku prac.** Nie sprawdzono:
  - eksportu z prawdziwego terminala (limit „Maks. słupków”, dostępność historii u brokera, rzeczywista konwencja DST serwera, symbol `BTCUSDT-`);
  - działania `32_CENTRUM_TRENINGU.bat` i limitu pamięci Job Object;
  - instalacji `pyarrow` z hashami na Windows (hashe pobrane z PyPI dla cp312/cp313 win_amd64).

  **Nie przeprowadzono testu rzeczywistego MT5 → eksport → trening → inferencja.** Procedura do wykonania u Ciebie:
  1. Uruchom bota.
  2. Centrum treningu → XAUUSD → Eksportuj dane (przyrostowo, 90 dni).
  3. Sprawdź tabelę luk (BRAKI powinny być nieliczne).
  4. Uruchom cały proces.
  5. Porównaj skill z modelem bazowym i ECE.
  6. Aktywuj tylko wersję z danymi „rzeczywiste” i skill > 0 w większości foldów.
  7. Obserwuj predykcje w sekcji 5 – są w trybie OBSERVATION.
  8. Powtórz dla BTC.
- **Jakość modeli nieznana.** Wszystkie przebiegi treningu tutaj to dane SYNTETYCZNE (symulator). Ich metryki, także dodatnia „ocena po kosztach”, **nic nie mówią o rynku**. Brak dowodu przewagi; nie obiecuję win rate ani ROI.
- **Prowizja**: z symulatora nieznana (brak transakcji), więc w etykietach testowych 0 z flagą `UNKNOWN_ZERO_USED`.
- **Strefy**: parametry (progi ATR, wagi jakości) to decyzje projektowe, nie wartości zwalidowane empirycznie. Jakość 0–100 nie jest skalibrowanym prawdopodobieństwem.
- **Pozostałe modele** (gold_candles, scalp A/B/C, legacy ML, lab, NSS, Structure Intelligence, flow, context, SH tp-model, PMW-MM): mają kod, trenery i stany w rejestrze, ale **żaden nie ma w tym środowisku artefaktu wytrenowanego na Twoich danych**.
  - Ich stany w panelu pochodzą z sond (najczęściej „niewytrenowany”).
  - Blokady specyfikacji PMW-MM (SDOm, Quant Momentum, Renko, H&S, Data Grabber, Chart Sync) bez zmian – brak plików specyfikacji.
- **Most do MT5 na innej maszynie** jest plikowy (eksport → kopia → import z weryfikacją). Połączenia sieciowego z obcym terminalem nie ma.
