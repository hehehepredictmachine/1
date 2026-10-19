# Scalp ML – wynik netto pełnego cyklu (PMW-UPD-03, SCALP_NET_PROFIT_MARKET_V1)

## Co przewiduje model
Dla **każdego kandydata scalp** (plan ScalpMachine po bramkach strategii, wejście MARKET) i osobno dla strony LONG / SHORT:

* klasyfikator XGBoost: **P(net_R całego cyklu > 0)** – po prowizji, poślizgu, Bid/Ask, z TP1/TP2, BE i wyjściem czasowym
  (polityka wyjść = `scalp/replay.py`); wynik dokładnie 0 → klasa 0,
* regresor XGBoost: **oczekiwany net_R** (średnia warunkowa).

To **nie** jest P(wzrost ceny), P(TP1 przed SL) ani sygnał wejścia. Kandydat bez wykonalnego wejścia (LIMIT niewypełniony,
brak danych) **nie jest stratą** – dostaje status NO_EXECUTABLE_ENTRY / DATA_GAP.

## Dane i cechy
* `SCALP-NET-FEAT-1.0.0` (`scalp/strategy.py::scalp_net_features`): cechy setupu bez konwencji „0 = brak” (brak → NaN + flaga
  `*_ok` / `*_known`) + blok M1 (zwroty, zakres, knoty, %B, EMA20 w jednostkach ATR(M1)) + spread/ryzyko. Tylko zamknięte świece ≤ sygnał.
* Trening: replay historii z eksportu `REAL_USER_DATA` (00_TRENING_START.bat) – wszystkie kandydaty, nie tylko wybrane.
* Live: `ml_scalp_samples` – każdy kandydat zapisany **raz** (setup × strona) przed jakimkolwiek filtrem modelu; etykieta dopisywana po
  zakończeniu cyklu tą samą funkcją `_outcome` co rozliczenie SHADOW. Predykcje (`ml_scalp_predictions`) z hashem modelu i TTL 120 s.

## Protokół
* Holdout = ostatnie 20 % kalendarza; rezerwowany w `eval_ledger` **przed** odczytem etykiet (ponowne użycie okresu →
  REUSED_PERIOD_EXPLORATORY, nigdy HOLDOUT_PASSED).
* Rozwój: 4 rozszerzające się foldy walk-forward; w każdym FIT 60 / TUNE 15 / CALIBRATION 15 / POLICY 10, purge po końcu etykiety
  + embargo = max hold, ten sam range nie przechodzi przez granicę.
* XGBoost CPU hist, 6 konfiguracji (głębokość 2/3/4 × lambda 5/10), early stopping 40 na TUNE, Platt na CALIBRATION, polityka
  p_min × ev_min (siatka 3×3) na POLICY. Baseline: prior, regresja logistyczna, małe drzewo; regresja: średnia, Ridge.
* Kryteria (`ml/scalp_task.py::CRITERIA`): ≥1000 kandydatów strony w rozwoju, zysk log loss w ≥75 % foldów, ECE ≤ 0.10, regresor lepszy
  od średniej, ≥100 wybranych cykli i ≥30 dni w holdoucie, dolna granica CI95 (bootstrap dzienny) > 0 dla polityki i dla przyrostu
  wobec baseline, wynik w scenariuszu stresu kosztów > 0. Dodatkowo pełny chronologiczny replay polityki (odrzucone kandydaty nie
  zajmują slotu).

## Artefakt i role
`data/ml_scalp/<INSTR>/runs/<run>/bundle_<BUY|SELL>/`: `classifier.ubj`, `regressor.ubj`, `preprocessor.json`, `calibrator.json`,
`policy.json`, `manifest.json` (sha256 każdego pliku, model_hash). Dane syntetyczne → `fixture_runs`, rola FIXTURE_ONLY, nie do wyboru.

Wybór jest **ręczny** i zakresowy (instrument × profil × strona): OBSERVE (tylko podgląd) albo SHADOW_GATE (hipotetyczny filtr –
wymaga HOLDOUT_PASSED). Żadna rola nie wysyła zleceń ani nie zmienia Execution Lock. Rollback przywraca poprzedni wybór całego bundla.

## Wyjaśnienia
„Dlaczego?” w panelu = TreeSHAP (`pred_contribs`) klasyfikatora w jednostkach **marginesu log-odds** (nie procent); sprawdzana suma
bias + wkłady = margines. Wyjaśnienie dla predykcji modelu, który już nie jest wybrany → MODEL_CHANGED (bez mieszania modeli).

## Obsługa
* `24_SCALP_ML.bat` – menu: doctor / status / prepare / train / raport / rollback.
* CLI: `python -m masterquo ml-scalp doctor|status|prepare|train|report|rollback|select --asset XAUUSD|BTC`.
* API: `GET /api/v1/ml/scalp?asset=`, `POST /api/v1/ml/scalp/prepare`, `POST /api/v1/ml/scalp/train` (job, activate=none),
  `GET /api/v1/ml/scalp/predictions`, `GET /api/v1/ml/scalp/explain?prediction_id=`, `POST /api/v1/ml/scalp/select`, `POST /api/v1/ml/scalp/rollback`.
* Panel: Modele i trening → karta „Scalp ML – wynik netto cyklu”. Runner treningu: zadanie `ml_scalp` (12 zadań na instrument).

## Stan (bez danych użytkownika)
Kod i testy na danych syntetycznych: gotowe. Trening na prawdziwych danych: NOT_RUN (brak eksportu MT5 w środowisku budowy).
Przewaga: NOT_EVALUATED. Precyzja replayu: OHLC_APPROX (bez ticków).
