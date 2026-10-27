# Mapa modeli i treningu (XAUUSD / BTC)

Wygenerowano przez `tools/model_map.py` (to samo źródło co `MAPA_MODELI_I_TRENINGU.json`).
Status opisuje stan KODU w tej paczce. Nie mówi nic o jakości modelu na Twoich danych – tę pokazuje dopiero raport runu treningu.
Jednostka modelu: instrument × zadanie × TF × horyzont × strona. Każdy instrument ma osobne dane, skalery, kalibratory, modele i rejestry.

## FORECAST_GOLD_CANDLES – Prognozy świec (gold_candles) – regresja logistyczna wieloklasowa + kalibracja + kwantyle GBR

- **Implementacja:** backend/gold_candles/model.py, gold_candles_runtime/plan_train.py
- **Zadanie:** rozkład kierunku zamknięcia DOWN/FLAT/UP (próg ±0.20×ATR) + kwantyle q10/q50/q90
- **Źródło danych:** eksport MT5 M5 + M30 dokładnego symbolu (czas serwera → UTC, zmierzony offset / NY_CLOSE)
- **TF:** M5 (+ kontekst M30 dołączany od available_at)
- **Horyzont:** 1/3/6 świec M5 = 5/15/30 min
- **Strona:** nie dotyczy (rozkład)
- **Cechy:** gold_candles/features.py (wzorce świec, ATR, pozycja w siatce grid_step z profilu instrumentu, kontekst M30)
- **Etykieta:** klasa zmiany ceny zamknięcia po h świecach względem ATR
- **Trainer:** gold_candles_runtime.plan_train (.venv_candles; plan zamrożony, fit/kalibracja/holdout chronologicznie)
- **Loader:** gold_candles_runtime.worker → gold_candles.model.forecast (bot: ForecastService, proces per instrument)
- **Artefakt:** XAUUSD: data/forecast/runs/<run>/forecast_model.json; BTC: data/instruments/BTC/forecast/runs/…; rejestr registry.json per instrument
- **Instrumenty:** XAUUSD, BTC
- **Status:** ZAIMPLEMENTOWANE_I_ZINTEGROWANE (XAUUSD: grid 5.0; BTC: grid 500 – hipoteza badawcza); parity loadera; brak testu na realnym MT5 w tym środowisku

## DOUBLE_RETEST_V2 – Maszyna stanów Double Retest v2

- **Implementacja:** masterquo/forecast/double_retest.py
- **Zadanie:** reguła setupu (bez trenowania)
- **Źródło danych:** bary bota
- **TF:** M5/M30
- **Horyzont:** —
- **Strona:** oba
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** brak (reguła)
- **Loader:** ForecastService
- **Artefakt:** —
- **Instrumenty:** XAUUSD, BTC
- **Status:** REGUŁA – nie jest modelem do trenowania

## SCALP_A – Scalp A – kierunek 1/3/5 min (BASELINE, LR, HGB, MLP 64-32, kwantyle HGB)

- **Implementacja:** gold_candles_runtime/scalp_train.py, scalp_features.py, scalp_infer.py
- **Zadanie:** klasa DOWN/FLAT/UP po kosztach (tau = max(0.2×ATR, koszt))
- **Źródło danych:** eksport M1 (+M5…H1 dla kontekstu replayu)
- **TF:** M1
- **Horyzont:** 1/3/5 min
- **Strona:** oba (klasy)
- **Cechy:** SCALP-FEAT-1.0.0 (zwroty, ATR, świeca, BB, SAR, wolumen, spread, sesja)
- **Etykieta:** zmiana ceny względem progu kosztowego
- **Trainer:** gold_candles_runtime.scalp_train --instrument (walk-forward 5 bloków, embargo, kalibracja, holdout)
- **Loader:** scalp_infer.ScalpModel przez worker (cmd scalp_forecast)
- **Artefakt:** data/scalp/runs/<run> (XAUUSD) | data/instruments/BTC/scalp/runs/<run>; registry.json per instrument
- **Instrumenty:** XAUUSD, BTC
- **Status:** ZAIMPLEMENTOWANE_I_ZINTEGROWANE; profil BTC = kopia reguł XAUUSD (wszystkie progi względne) jako hipoteza

## SCALP_B – Scalp B – jakość setupu P(TP1 przed SL) (LR, HGB)

- **Implementacja:** gold_candles_runtime/scalp_train.py train_setup_model
- **Zadanie:** P(TP1 przed SL) cyklu Range→Sweep→Retest
- **Źródło danych:** cykle z replayu profilu scalp na eksporcie
- **TF:** M1/M5
- **Horyzont:** do 30 min (max_hold)
- **Strona:** BUY i SELL (cecha kierunku)
- **Cechy:** cechy cyklu z replayu
- **Etykieta:** tp1_before_sl
- **Trainer:** scalp_train (te same bloki czasowe)
- **Loader:** scalp_infer.SetupModel (worker setup_quality)
- **Artefakt:** jak Scalp A
- **Instrumenty:** XAUUSD, BTC
- **Status:** ZAIMPLEMENTOWANE; zwykle BRAK_PRZESLANEK przy małej liczbie cykli

## SCALP_C – Scalp C – ocena polityki HEDGE_PARTIAL vs REDUCE

- **Implementacja:** masterquo/scalp/replay.py, report.hedge_summary
- **Zadanie:** porównanie polityk w replayu OHLC (bez ticków) – NIE jest siecią ani klasyfikatorem
- **Źródło danych:** replay eksportu M1
- **TF:** M1
- **Horyzont:** cykl
- **Strona:** oba
- **Cechy:** —
- **Etykieta:** wynik R polityk
- **Trainer:** brak (ewaluacja polityki)
- **Loader:** —
- **Artefakt:** raport runu scalp
- **Instrumenty:** XAUUSD, BTC
- **Status:** EWALUACJA_POLITYKI – hedge pozostaje SHADOW/REDUCE

## SCALP_PROFILE – Profil scalp Range→Sweep→Retest (automat stanów)

- **Implementacja:** masterquo/scalp/strategy.py + config/scalp_profile_v1.json / scalp_profile_BTC_v1.json
- **Zadanie:** reguła
- **Źródło danych:** bary bota
- **TF:** H1/M30/M15 kontekst, M5 zakres, M1 wyzwalacz
- **Horyzont:** —
- **Strona:** oba
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** brak
- **Loader:** ScalpService (profil per aktywne aktywo)
- **Artefakt:** —
- **Instrumenty:** XAUUSD, BTC
- **Status:** REGUŁA

## LEGACY_ML_DT – Legacy ML – Decision Tree

- **Implementacja:** masterquo/ml/{features,labels,models,trainer,registry,service,router,offline}.py
- **Zadanie:** P(setup S01–S12 osiąga cel netto przed SL) dla potwierdzonej wersji setupu
- **Źródło danych:** setupy silnika na żywo (HIGH) + backfill z eksportu (APPROX, tylko gdy zadanie o to prosi)
- **TF:** TF setupu
- **Horyzont:** do wyjścia setupu
- **Strona:** oba (cecha kierunku)
- **Cechy:** MQ-FEAT-1.1.0 (ml/features.py; 1.0.0 + cechy stref PMW-ZONE-FEAT-1)
- **Etykieta:** MQ-LABEL-1.1.0 (koszty: spread+poślizg+prowizja)
- **Trainer:** ml/trainer.py (bloki fit/tune/calibrate/test, embargo 120 min); offline: training ml-offline
- **Loader:** ml/registry.py Bundle → MLService.predict (bot, baza aktywnego instrumentu)
- **Artefakt:** XAUUSD: data/ml/models + masterquo.sqlite; BTC: data/instruments/BTC/ml/{models,ml.sqlite}
- **Instrumenty:** XAUUSD, BTC
- **Status:** ZINTEGROWANE per instrument; model z próbek APPROX = RESEARCH_APPROX (nigdy champion automatycznie)

## LEGACY_ML_XGB – Legacy ML – XGBoost (CPU)

- **Implementacja:** jak LEGACY_ML_DT
- **Zadanie:** jak LEGACY_ML_DT
- **Źródło danych:** jak LEGACY_ML_DT
- **TF:** TF setupu
- **Horyzont:** do wyjścia setupu
- **Strona:** oba
- **Cechy:** MQ-FEAT-1.1.0
- **Etykieta:** MQ-LABEL-1.1.0
- **Trainer:** ml/trainer.py
- **Loader:** ml/registry.py
- **Artefakt:** jak LEGACY_ML_DT
- **Instrumenty:** XAUUSD, BTC
- **Status:** jak LEGACY_ML_DT

## LAB_DUMMY – Lab DUMMY – częstość bazowa

- **Implementacja:** masterquo/lab/protocol.py fit_family('DUMMY'), lab/nets.py, lab/minirocket.py
- **Zadanie:** klasyfikacja binarna LONG
- **Źródło danych:** eksport treningowy M5 (data/training/datasets/<INST>/<run>) albo bufor bota
- **TF:** M5
- **Horyzont:** 12 świec (60 min)
- **Strona:** LONG (tylko długie – nie oznaczać jako oba kierunki)
- **Cechy:** FS-1.0.0 (lab/features.py: zwroty, ATR, EMA gap, kinematyka, sesja; sekwencje 32×kanały dla sieci)
- **Etykieta:** potrójna bariera: TP 1.5×ATR przed SL 1.0×ATR w 12 świecach M5 (LBL-TB-1.0.0); SL i TP w tej samej świecy → SL (konserwatywnie)
- **Trainer:** masterquo/lab/protocol.py LabTrainer + training lab-offline (walk-forward 4 foldy, purge/embargo 12, holdout 20% raz)
- **Loader:** lab/protocol.py load_artifact → LabService._infer (bot), kontrola parity przy zapisie
- **Artefakt:** data/lab/models/<INST>/<model_id>/model.pkl + manifest.json (+ ACTIVE.json: aktywny per rodzina, rollback)
- **Instrumenty:** XAUUSD, BTC
- **Status:** MODEL_KONTROLNY (nie zapisywany jako artefakt); zapisywany jest model oceniany (fit na danych rozwojowych), bez refitu na train+holdout

## LAB_RULE – Lab RULE – reguła odniesienia

- **Implementacja:** masterquo/lab/protocol.py fit_family('RULE'), lab/nets.py, lab/minirocket.py
- **Zadanie:** klasyfikacja binarna LONG
- **Źródło danych:** eksport treningowy M5 (data/training/datasets/<INST>/<run>) albo bufor bota
- **TF:** M5
- **Horyzont:** 12 świec (60 min)
- **Strona:** LONG (tylko długie – nie oznaczać jako oba kierunki)
- **Cechy:** FS-1.0.0 (lab/features.py: zwroty, ATR, EMA gap, kinematyka, sesja; sekwencje 32×kanały dla sieci)
- **Etykieta:** potrójna bariera: TP 1.5×ATR przed SL 1.0×ATR w 12 świecach M5 (LBL-TB-1.0.0); SL i TP w tej samej świecy → SL (konserwatywnie)
- **Trainer:** masterquo/lab/protocol.py LabTrainer + training lab-offline (walk-forward 4 foldy, purge/embargo 12, holdout 20% raz)
- **Loader:** lab/protocol.py load_artifact → LabService._infer (bot), kontrola parity przy zapisie
- **Artefakt:** data/lab/models/<INST>/<model_id>/model.pkl + manifest.json (+ ACTIVE.json: aktywny per rodzina, rollback)
- **Instrumenty:** XAUUSD, BTC
- **Status:** MODEL_KONTROLNY; zapisywany jest model oceniany (fit na danych rozwojowych), bez refitu na train+holdout

## LAB_LOGREG – Lab regresja logistyczna

- **Implementacja:** masterquo/lab/protocol.py fit_family('LOGREG'), lab/nets.py, lab/minirocket.py
- **Zadanie:** klasyfikacja binarna LONG
- **Źródło danych:** eksport treningowy M5 (data/training/datasets/<INST>/<run>) albo bufor bota
- **TF:** M5
- **Horyzont:** 12 świec (60 min)
- **Strona:** LONG (tylko długie – nie oznaczać jako oba kierunki)
- **Cechy:** FS-1.0.0 (lab/features.py: zwroty, ATR, EMA gap, kinematyka, sesja; sekwencje 32×kanały dla sieci)
- **Etykieta:** potrójna bariera: TP 1.5×ATR przed SL 1.0×ATR w 12 świecach M5 (LBL-TB-1.0.0); SL i TP w tej samej świecy → SL (konserwatywnie)
- **Trainer:** masterquo/lab/protocol.py LabTrainer + training lab-offline (walk-forward 4 foldy, purge/embargo 12, holdout 20% raz)
- **Loader:** lab/protocol.py load_artifact → LabService._infer (bot), kontrola parity przy zapisie
- **Artefakt:** data/lab/models/<INST>/<model_id>/model.pkl + manifest.json (+ ACTIVE.json: aktywny per rodzina, rollback)
- **Instrumenty:** XAUUSD, BTC
- **Status:** ZAIMPLEMENTOWANE_I_ZINTEGROWANE; zapisywany jest model oceniany (fit na danych rozwojowych), bez refitu na train+holdout

## LAB_TREE – Lab drzewo decyzyjne (≠ legacy Decision Tree: inne pytanie – bariera LONG M5, nie setup S01–S12)

- **Implementacja:** masterquo/lab/protocol.py fit_family('TREE'), lab/nets.py, lab/minirocket.py
- **Zadanie:** klasyfikacja binarna LONG
- **Źródło danych:** eksport treningowy M5 (data/training/datasets/<INST>/<run>) albo bufor bota
- **TF:** M5
- **Horyzont:** 12 świec (60 min)
- **Strona:** LONG (tylko długie – nie oznaczać jako oba kierunki)
- **Cechy:** FS-1.0.0 (lab/features.py: zwroty, ATR, EMA gap, kinematyka, sesja; sekwencje 32×kanały dla sieci)
- **Etykieta:** potrójna bariera: TP 1.5×ATR przed SL 1.0×ATR w 12 świecach M5 (LBL-TB-1.0.0); SL i TP w tej samej świecy → SL (konserwatywnie)
- **Trainer:** masterquo/lab/protocol.py LabTrainer + training lab-offline (walk-forward 4 foldy, purge/embargo 12, holdout 20% raz)
- **Loader:** lab/protocol.py load_artifact → LabService._infer (bot), kontrola parity przy zapisie
- **Artefakt:** data/lab/models/<INST>/<model_id>/model.pkl + manifest.json (+ ACTIVE.json: aktywny per rodzina, rollback)
- **Instrumenty:** XAUUSD, BTC
- **Status:** ZAIMPLEMENTOWANE_I_ZINTEGROWANE; zapisywany jest model oceniany (fit na danych rozwojowych), bez refitu na train+holdout

## LAB_MINIROCKET – Lab MiniRocket (numpy) + klasyfikator liniowy

- **Implementacja:** masterquo/lab/protocol.py fit_family('MINIROCKET'), lab/nets.py, lab/minirocket.py
- **Zadanie:** klasyfikacja binarna LONG
- **Źródło danych:** eksport treningowy M5 (data/training/datasets/<INST>/<run>) albo bufor bota
- **TF:** M5
- **Horyzont:** 12 świec (60 min)
- **Strona:** LONG (tylko długie – nie oznaczać jako oba kierunki)
- **Cechy:** FS-1.0.0 (lab/features.py: zwroty, ATR, EMA gap, kinematyka, sesja; sekwencje 32×kanały dla sieci)
- **Etykieta:** potrójna bariera: TP 1.5×ATR przed SL 1.0×ATR w 12 świecach M5 (LBL-TB-1.0.0); SL i TP w tej samej świecy → SL (konserwatywnie)
- **Trainer:** masterquo/lab/protocol.py LabTrainer + training lab-offline (walk-forward 4 foldy, purge/embargo 12, holdout 20% raz)
- **Loader:** lab/protocol.py load_artifact → LabService._infer (bot), kontrola parity przy zapisie
- **Artefakt:** data/lab/models/<INST>/<model_id>/model.pkl + manifest.json (+ ACTIVE.json: aktywny per rodzina, rollback)
- **Instrumenty:** XAUUSD, BTC
- **Status:** ZAIMPLEMENTOWANE_I_ZINTEGROWANE; zapisywany jest model oceniany (fit na danych rozwojowych), bez refitu na train+holdout

## LAB_XGB – Lab XGBoost (CPU)

- **Implementacja:** masterquo/lab/protocol.py fit_family('XGB'), lab/nets.py, lab/minirocket.py
- **Zadanie:** klasyfikacja binarna LONG
- **Źródło danych:** eksport treningowy M5 (data/training/datasets/<INST>/<run>) albo bufor bota
- **TF:** M5
- **Horyzont:** 12 świec (60 min)
- **Strona:** LONG (tylko długie – nie oznaczać jako oba kierunki)
- **Cechy:** FS-1.0.0 (lab/features.py: zwroty, ATR, EMA gap, kinematyka, sesja; sekwencje 32×kanały dla sieci)
- **Etykieta:** potrójna bariera: TP 1.5×ATR przed SL 1.0×ATR w 12 świecach M5 (LBL-TB-1.0.0); SL i TP w tej samej świecy → SL (konserwatywnie)
- **Trainer:** masterquo/lab/protocol.py LabTrainer + training lab-offline (walk-forward 4 foldy, purge/embargo 12, holdout 20% raz)
- **Loader:** lab/protocol.py load_artifact → LabService._infer (bot), kontrola parity przy zapisie
- **Artefakt:** data/lab/models/<INST>/<model_id>/model.pkl + manifest.json (+ ACTIVE.json: aktywny per rodzina, rollback)
- **Instrumenty:** XAUUSD, BTC
- **Status:** ZAIMPLEMENTOWANE_I_ZINTEGROWANE; zapisywany jest model oceniany (fit na danych rozwojowych), bez refitu na train+holdout

## LAB_RESNET1D – Lab ResNet1D (numpy)

- **Implementacja:** masterquo/lab/protocol.py fit_family('RESNET1D'), lab/nets.py, lab/minirocket.py
- **Zadanie:** klasyfikacja binarna LONG
- **Źródło danych:** eksport treningowy M5 (data/training/datasets/<INST>/<run>) albo bufor bota
- **TF:** M5
- **Horyzont:** 12 świec (60 min)
- **Strona:** LONG (tylko długie – nie oznaczać jako oba kierunki)
- **Cechy:** FS-1.0.0 (lab/features.py: zwroty, ATR, EMA gap, kinematyka, sesja; sekwencje 32×kanały dla sieci)
- **Etykieta:** potrójna bariera: TP 1.5×ATR przed SL 1.0×ATR w 12 świecach M5 (LBL-TB-1.0.0); SL i TP w tej samej świecy → SL (konserwatywnie)
- **Trainer:** masterquo/lab/protocol.py LabTrainer + training lab-offline (walk-forward 4 foldy, purge/embargo 12, holdout 20% raz)
- **Loader:** lab/protocol.py load_artifact → LabService._infer (bot), kontrola parity przy zapisie
- **Artefakt:** data/lab/models/<INST>/<model_id>/model.pkl + manifest.json (+ ACTIVE.json: aktywny per rodzina, rollback)
- **Instrumenty:** XAUUSD, BTC
- **Status:** ZAIMPLEMENTOWANE_I_ZINTEGROWANE; zapisywany jest model oceniany (fit na danych rozwojowych), bez refitu na train+holdout

## LAB_SEW_SNN – Lab SEW-SNN (sieć impulsowa, numpy)

- **Implementacja:** masterquo/lab/protocol.py fit_family('SEW_SNN'), lab/nets.py, lab/minirocket.py
- **Zadanie:** klasyfikacja binarna LONG
- **Źródło danych:** eksport treningowy M5 (data/training/datasets/<INST>/<run>) albo bufor bota
- **TF:** M5
- **Horyzont:** 12 świec (60 min)
- **Strona:** LONG (tylko długie – nie oznaczać jako oba kierunki)
- **Cechy:** FS-1.0.0 (lab/features.py: zwroty, ATR, EMA gap, kinematyka, sesja; sekwencje 32×kanały dla sieci)
- **Etykieta:** potrójna bariera: TP 1.5×ATR przed SL 1.0×ATR w 12 świecach M5 (LBL-TB-1.0.0); SL i TP w tej samej świecy → SL (konserwatywnie)
- **Trainer:** masterquo/lab/protocol.py LabTrainer + training lab-offline (walk-forward 4 foldy, purge/embargo 12, holdout 20% raz)
- **Loader:** lab/protocol.py load_artifact → LabService._infer (bot), kontrola parity przy zapisie
- **Artefakt:** data/lab/models/<INST>/<model_id>/model.pkl + manifest.json (+ ACTIVE.json: aktywny per rodzina, rollback)
- **Instrumenty:** XAUUSD, BTC
- **Status:** ZAIMPLEMENTOWANE_I_ZINTEGROWANE; zapisywany jest model oceniany (fit na danych rozwojowych), bez refitu na train+holdout

## LAB_LOGREG_PCA – Eksperyment: LOGREG na PCA

- **Implementacja:** masterquo/lab/protocol.py fit_family('LOGREG_PCA'), lab/nets.py, lab/minirocket.py
- **Zadanie:** klasyfikacja binarna LONG
- **Źródło danych:** eksport treningowy M5 (data/training/datasets/<INST>/<run>) albo bufor bota
- **TF:** M5
- **Horyzont:** 12 świec (60 min)
- **Strona:** LONG (tylko długie – nie oznaczać jako oba kierunki)
- **Cechy:** FS-1.0.0 (lab/features.py: zwroty, ATR, EMA gap, kinematyka, sesja; sekwencje 32×kanały dla sieci)
- **Etykieta:** potrójna bariera: TP 1.5×ATR przed SL 1.0×ATR w 12 świecach M5 (LBL-TB-1.0.0); SL i TP w tej samej świecy → SL (konserwatywnie)
- **Trainer:** masterquo/lab/protocol.py LabTrainer + training lab-offline (walk-forward 4 foldy, purge/embargo 12, holdout 20% raz)
- **Loader:** lab/protocol.py load_artifact → LabService._infer (bot), kontrola parity przy zapisie
- **Artefakt:** data/lab/models/<INST>/<model_id>/model.pkl + manifest.json (+ ACTIVE.json: aktywny per rodzina, rollback)
- **Instrumenty:** XAUUSD, BTC
- **Status:** EKSPERYMENT; zapisywany jest model oceniany (fit na danych rozwojowych), bez refitu na train+holdout

## LAB_LOGREG_GMM_AUG – Eksperyment: LOGREG z cechami reżimu GMM

- **Implementacja:** masterquo/lab/protocol.py fit_family('LOGREG_GMM_AUG'), lab/nets.py, lab/minirocket.py
- **Zadanie:** klasyfikacja binarna LONG
- **Źródło danych:** eksport treningowy M5 (data/training/datasets/<INST>/<run>) albo bufor bota
- **TF:** M5
- **Horyzont:** 12 świec (60 min)
- **Strona:** LONG (tylko długie – nie oznaczać jako oba kierunki)
- **Cechy:** FS-1.0.0 (lab/features.py: zwroty, ATR, EMA gap, kinematyka, sesja; sekwencje 32×kanały dla sieci)
- **Etykieta:** potrójna bariera: TP 1.5×ATR przed SL 1.0×ATR w 12 świecach M5 (LBL-TB-1.0.0); SL i TP w tej samej świecy → SL (konserwatywnie)
- **Trainer:** masterquo/lab/protocol.py LabTrainer + training lab-offline (walk-forward 4 foldy, purge/embargo 12, holdout 20% raz)
- **Loader:** lab/protocol.py load_artifact → LabService._infer (bot), kontrola parity przy zapisie
- **Artefakt:** data/lab/models/<INST>/<model_id>/model.pkl + manifest.json (+ ACTIVE.json: aktywny per rodzina, rollback)
- **Instrumenty:** XAUUSD, BTC
- **Status:** EKSPERYMENT; zapisywany jest model oceniany (fit na danych rozwojowych), bez refitu na train+holdout

## LAB_LOGREG_NEUTRALIZED – Eksperyment: LOGREG z neutralizacją czynników

- **Implementacja:** masterquo/lab/protocol.py fit_family('LOGREG_NEUTRALIZED'), lab/nets.py, lab/minirocket.py
- **Zadanie:** klasyfikacja binarna LONG
- **Źródło danych:** eksport treningowy M5 (data/training/datasets/<INST>/<run>) albo bufor bota
- **TF:** M5
- **Horyzont:** 12 świec (60 min)
- **Strona:** LONG (tylko długie – nie oznaczać jako oba kierunki)
- **Cechy:** FS-1.0.0 (lab/features.py: zwroty, ATR, EMA gap, kinematyka, sesja; sekwencje 32×kanały dla sieci)
- **Etykieta:** potrójna bariera: TP 1.5×ATR przed SL 1.0×ATR w 12 świecach M5 (LBL-TB-1.0.0); SL i TP w tej samej świecy → SL (konserwatywnie)
- **Trainer:** masterquo/lab/protocol.py LabTrainer + training lab-offline (walk-forward 4 foldy, purge/embargo 12, holdout 20% raz)
- **Loader:** lab/protocol.py load_artifact → LabService._infer (bot), kontrola parity przy zapisie
- **Artefakt:** data/lab/models/<INST>/<model_id>/model.pkl + manifest.json (+ ACTIVE.json: aktywny per rodzina, rollback)
- **Instrumenty:** XAUUSD, BTC
- **Status:** EKSPERYMENT; zapisywany jest model oceniany (fit na danych rozwojowych), bez refitu na train+holdout

## MONTE_CARLO_PATHS – Monte Carlo ścieżek cen (PMW-MC-1) – P(TP przed SL w horyzoncie)

- **Implementacja:** masterquo/montecarlo/engine.py, validate.py, service.py
- **Zadanie:** prawdopodobieństwo, że cena dojdzie do TP przed SL w H świecach M1 (każdy poziom osobno) + zasięg ruchu ±X; świeca z TP i SL = przedział ostrożny–optymistyczny
- **Źródło danych:** zamknięte świece M1 bota (na żywo) / eksport MT5 M1 (+ opcjonalne ticki Bid/Ask rozstrzygające kolejność w świecy) – walidacja
- **TF:** M1
- **Horyzont:** H świec M1 (domyślnie 60; scenariusz SCALPING 30)
- **Strona:** BUY i SELL – strona Bid/Ask, spread ze świecy
- **Cechy:** brak cech uczonych: losowanie całych świec (OHLC względem otwarcia) – IID / blokowe / warunkowane reżimem ATR i godziną sesji, skalowane do bieżącego ATR
- **Etykieta:** rzeczywiste TP przed SL w H świecach (walidacja; ticki, gdy są) – dane wyłącznie sprzed chwili oceny
- **Trainer:** `python -m masterquo montecarlo validate` / 31_MONTE_CARLO_WALIDACJA.bat / zadanie runnera monte_carlo: walk-forward CAL/TEST z embargo H, model bazowy = klimatologia, Brier / log loss / kalibracja, CI bootstrap, kalibrator izotoniczny
- **Loader:** MonteCarloService (własny wątek; bufor zamkniętych świec bota) → /api/v1/montecarlo/*, /api/v1/sh/scenario
- **Artefakt:** data/montecarlo/<INST>/registry.json + runs/<run>/report.json (aktywny kalibrator tylko z REAL_USER_DATA z przewagą; rollback: montecarlo rollback)
- **Instrumenty:** XAUUSD, BTC
- **Status:** ZAIMPLEMENTOWANE_I_ZINTEGROWANE; bez kalibracji = prawdopodobieństwo w modelu (tak opisane w panelu); walidacja tylko na danych syntetycznych w tym środowisku (werdykt TEST_TECHNICZNY)

## LAB_MARKOV – Macierz Markowa 3 stanów (moduł estymowany)

- **Implementacja:** masterquo/lab/market.py markov()
- **Zadanie:** rozkład stanu następnej świecy
- **Źródło danych:** bary bota
- **TF:** M5
- **Horyzont:** 1 świeca
- **Strona:** nie dotyczy
- **Cechy:** zwrot close-to-close
- **Etykieta:** stan DOWN/FLAT/UP
- **Trainer:** estymacja w oknie 500 świec kończącym się na ostatniej zamkniętej (wygładzanie Laplace'a) – bez osobnego treningu
- **Loader:** LabService (na żywo)
- **Artefakt:** —
- **Instrumenty:** XAUUSD, BTC
- **Status:** ESTYMOWANY_ONLINE; walidacja: archiwum prognoz punkt-w-czasie (Dane i diagnostyka)

## LAB_ACD – ACD(1,1) aktywności ticków (moduł estymowany)

- **Implementacja:** masterquo/lab/ticks.py fit_acd()
- **Zadanie:** oczekiwany czas do kolejnego ticka
- **Źródło danych:** ticki copy_ticks_from
- **TF:** tick
- **Horyzont:** następne zdarzenie
- **Strona:** nie dotyczy
- **Cechy:** czasy między tickami skorygowane dobowo
- **Etykieta:** —
- **Trainer:** QMLE wykładnicze, ograniczenia a+b<1 z konstrukcji – estymacja online
- **Loader:** LabService
- **Artefakt:** —
- **Instrumenty:** XAUUSD, BTC
- **Status:** ESTYMOWANY_ONLINE; minimum 300 zdarzeń, inaczej warming_up

## INDICATORS_FFT_VMD_EMD – Wskaźniki, FFT/VMD/EMD, BB/MA, Double Bottom

- **Implementacja:** masterquo/analytics/*, strategies/indicators.py
- **Zadanie:** obliczenia – nie są sieciami i nie mają przycisku „trenuj”
- **Źródło danych:** bary bota
- **TF:** różne
- **Horyzont:** —
- **Strona:** —
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** brak
- **Loader:** AnalyticsService
- **Artefakt:** —
- **Instrumenty:** XAUUSD, BTC
- **Status:** OBLICZENIA

## STRATEGIES_S01_S12 – Strategie S01–S12

- **Implementacja:** masterquo/strategies/*
- **Zadanie:** reguły setupów (strumień dla legacy ML)
- **Źródło danych:** bary bota / backfill z eksportu z symbolem instrumentu
- **TF:** M5–D1
- **Horyzont:** —
- **Strona:** oba
- **Cechy:** —
- **Etykieta:** —
- **Trainer:** brak
- **Loader:** ActiveEngine
- **Artefakt:** —
- **Instrumenty:** XAUUSD, BTC
- **Status:** REGUŁY
