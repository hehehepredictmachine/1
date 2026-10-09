# ML w MasterQUO AI 1.3 – Decision Tree + XGBoost

Model **nie generuje własnych sygnałów**. Ocenia kandydatów (setupy) wytworzonych przez strategie S01–S10.
Komentarz Claude nie jest etykietą. Model nigdy nie wywołuje `order_send` – zlecenia idą tylko przez centralny gateway.

## Przepływ
```
MT5 bridge → walidacja danych (EngineService) → skan S01–S10 (ActiveEngine) → SetupTracker
  → KOLEKTOR: próbka przy pierwszym CONFIRMED każdej wersji setupu (także nie wybranej / zablokowanej)  [ml/service.py]
  → FeatureEngine as-of czasu decyzji (wspólny dla treningu i predykcji)                                   [ml/features.py]
  → ETYKIETOWANIE przyrostowe z zamkniętych świec M1 + zapisanych kwotowań                                 [ml/labels.py]
  → SNAPSHOT niezmienny (JSONL.gz + manifest SHA-256)                                                     [ml/dataset.py]
  → TRENER w osobnym procesie (lock, limit czasu, anulowanie, wznowienie na tym samym snapshocie)          [ml/trainer.py]
  → WALIDACJA chronologiczna z purgingiem/embargo                                                        [ml/validation.py]
  → REJESTR champion/challenger, atomowa zamiana, rollback                                                [ml/registry.py]
  → PREDYKCJE (kontrakt) → węzeł ML drzewa decyzji / ranking AUTO (tylko ASSIST) → ryzyko → gateway
  → MONITORING: PSI cech, Brier na dojrzałych etykietach → DEGRADED → strategie bez ML
```

## Jednostka danych i etykieta
* Próbka = setup (wersja) w punkcie decyzji: `sample_id = setup_id:wersja`, `event_id` (zdarzenie rynkowe), symbol, `feed_id`,
  strategia i jej wersja, kierunek, TF, `asof_utc`, cechy (MQ-FEAT-1.0.0), plan wejścia/SL/TP/horyzont, `cost_model_version`
  (MQ-COST-1.0.0), `label_policy_version` (MQ-LABEL-1.0.0), status, `label_end_utc`, `label_known_utc`, źródło wyniku.
* Cel (ten sam dla obu modeli): **czy setup wykonany wg planu zapisanego przy jego powstaniu zakończy się wynikiem netto > 0**
  (1) czy ≤ 0 (0). Zapisywane też R, MFE, MAE, powód wyjścia. To nie jest „prawdopodobieństwo wzrostu ceny”.
* Wejście: otwarcie pierwszej M1 po czasie decyzji; LONG po Ask (+spread, +poślizg), SHORT po Bid; wyjścia LONG po Bid, SHORT po Ask.
* SL i TP w jednej M1: rozstrzyga zapis kwotowań z tej minuty; bez nich **AMBIGUOUS** (nigdy „na pewno strata”).
* Statusy bez etykiety: NO_ENTRY (brak świecy w oknie / wejście za stopem), NO_ENTRY (brak poziomów), MISSING_DATA (luka 15–50 min,
  historia poza buforem), AMBIGUOUS, UNRESOLVED (brak danych do terminu). Przerwy ≥ 50 min = przerwa sesji.
* Częściowe zamknięcia (TP1 z wagą, potem stop na BE) są w etykiecie. Zrealizowane transakcje PAPER/DEMO/LIVE są dołączane osobno
  (`realized_json`, atrybucja UNIQUE / MULTIPLE_POSITIONS_FOR_SETUP) – nie nadpisują etykiety hipotetycznej.
* Backfill z historii (MT5 lub symulator) = ta sama logika, tylko dane dostępne w danym momencie; jakość **APPROX**, domyślnie
  wyłączony z treningu (`ml.use_backfill_approx`). Dane syntetyczne i rzeczywiste nigdy się nie mieszają.

## Cechy (MQ-FEAT-1.0.0)
Per TF M5/M15/H1: zwroty w ATR, ATR%, ATR5/ATR50, RSI (dla SHORT odbite), MACD-hist/ATR, nachylenie EMA20, odległość od EMA20/50,
ER(20), percentyl szerokości BB, pozycja w Donchianie, budowa świecy, **tylko potwierdzone pivoty** (odległość, wiek), aktywność ticków.
H4/D1: kierunek, nachylenie, ER. Globalne: spread/ATR, czas (sin/cos, dzień, sesje), ryzyko w ATR, RR, liczba celów, punkty ACTIVE,
kontrtrend, konflikty TF. Kategorie: strategia, kierunek, TF, reżim, rodzina. Każdy TF przycinany do świec zamkniętych ≤ czas decyzji.
Braki zostają brakami (NaN – DT ≥ 1.3 i XGBoost obsługują je natywnie), nigdy 0. Preprocessing (wybór kolumn, kategorie, rozkłady
referencyjne dla PSI) uczony tylko na bloku FIT i zapisywany razem z modelem.

## Trening i walidacja
* Bloki w czasie: FIT 50% | TUNE 15% | CALIB 15% | TEST 20%. Bez mieszania. Całe zdarzenie (event_id) w jednym bloku.
  **Purging** wg rzeczywistego `label_end_utc` + **embargo** (domyślnie 120 min). Test musi zaczynać się po poprzednio użytym teście.
* Minimalne liczności każdego bloku i klasy (60 / 10) – inaczej NOT_READY z dokładnym powodem.
* Decision Tree: `max_depth`, `min_samples_leaf`, `min_samples_split`, `class_weight`, `ccp_alpha` wybierane na foldach walk-forward
  w FIT+TUNE (budżet 24 prób, `random_state` zapisany), eksport struktury drzewa, ścieżka decyzji i liczności liścia.
* XGBoost: `hist` CPU, limit wątków (2), `scale_pos_weight`, regularyzacja, subsample, early stopping na późniejszym bloku TUNE,
  zapis natywny `model.ubj`, TreeSHAP (`pred_contribs`) liczone na żądanie, poza ścieżką krytyczną.
* Kalibracja na bloku CALIB (izotoniczna przy ≥ 200 i ≥ 30/klasę, inaczej sigmoid; przy jednej klasie: NONE – bez udawanego 50%).
  Próg handlowy wybierany na CALIB, test oceniany raz.
* Porównanie na tym samym teście: częstość bazowa, prior strategii, polityka „wszystkie setupy bez ML”. Metryki: liczności klas,
  precision/recall, macierz pomyłek, PR-AUC, log loss, Brier, krzywa kalibracji + ECE (N/A dla jednej klasy), wynik polityki po kosztach
  (netto R, średnie R, max DD, ekspozycja, liczba transakcji – jedna pozycja naraz), bootstrap blokowy, rozbicia wg strategii/sesji/
  kierunku/reżimu z flagą małej próby.
* **Promocja** (kryteria w konfiguracji, kopiowane do raportu przed oceną): ≥ 150 próbek testu, ≥ 30 na klasę, Brier nie gorszy od
  częstości bazowej, skalibrowany, ECE ≤ 0,10, średnie R nie gorsze niż bez ML, DD nie większy o > 2 R, **lepszy Brier niż champion
  na tym samym nowym teście**. Złożoność nie jest kryterium. Zamiana atomowa (model + preprocessing + kalibrator); rollback przywraca całość.

## Tryby i kontrakt predykcji
* `ml.mode`: OFF (brak), SHADOW (liczy i zapisuje, nie wpływa – domyślny), ASSIST (węzeł ML blokuje setup poniżej progu, ranking AUTO
  dostaje premię `(p − częstość bazowa)`; wynik strategii nie jest liczony podwójnie). Ensemble – dopiero po osobnej walidacji OOS (wyłączony).
* Kontrakt `MQ-ML-PRED-1.0.0`: setup_id, wersja, model_id, rodzina, wersja modelu, feature_schema_version, asof_utc, raw_score,
  calibrated_probability, calibration_status, threshold, target_definition, readiness, uncertainty_reason, data_quality, explanation_ref.
* Brak modelu / błąd / DEGRADED / nieznana kategoria / dużo braków → readiness ≠ READY → bot działa na strategiach bez ML.
  `expected_net_R` nie jest podawane (brak zweryfikowanej metody) – N/A.
* Otwarte pozycje zachowują swój plan; każda predykcja jest zapisana z identyfikatorem modelu (`ml_predictions`).

## Harmonogram (wartości startowe, `config.ml`)
Sprawdzenie gotowości co 60 s; pierwszy trening ≥ 1000 unikalnych setupów z etykietą i ≥ 100 na klasę; kolejne po 250 nowych etykietach
i ≥ 6 h; limit treningu 30 min. „Trenuj teraz” pomija tylko czas oczekiwania. „Gotowy do nauki” ≠ wytrenowany model.
