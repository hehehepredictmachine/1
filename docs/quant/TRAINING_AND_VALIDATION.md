# Trening i walidacja – Quant MetaModel (PMW-QUANT-META-1)

## Skąd są dane

Każdy kandydat setupu obu ścieżek (ACTIVE S01–S12, SCALPING/HEDGING, scalp SHADOW) przechodzi przez `EvaluationService`. Po zapisie oceny Quant zapisuje w `<dane>/quant/ledger.sqlite` wiersz z:

- cechami **dostępnymi w chwili decyzji**: tylko rekordy opublikowanej generacji z `available_at`/`data_time` ≤ chwila decyzji (+5 s tolerancji zegara);
- EventSpec;
- identyfikatorem snapshotu i generacji;
- typem danych REAL/SYNTHETIC.

Po upływie horyzontu wiersz otrzymuje etykietę z symulatora planu na zamkniętych świecach M1 (`QuantService.mature`, co 30 s).

Prognozy modeli bazowych w ledgerze to wyniki **na żywo**, zapisane przed poznaniem wyniku. Są więc out-of-sample względem przyszłych etykiet.
Prognoz modelu wytrenowanego na całej historii nie wolno podstawiać jako historycznych OOF. Dlatego meta-model **nie** jest uczony na odtworzonej historii.
Bez dojrzałego ledgera status brzmi `INSUFFICIENT_EVIDENCE`.

## Cechy (`quant/features.py`)

Cechy są nazwane i wyrównane do strony transakcji. Każda ma maskę braku `m:<cecha>`.

| Prefiks | Znaczenie |
|---|---|
| `fc:<model>:<zadanie>:<TF>:edge` | P(strona) − P(przeciwna) rozkładu kierunku |
| `…:z` | średnia/sd prognozy zwrotu |
| `…:score`, `…:score_x_side` | surowy score (lab) |
| `st:<model>:aligned` | stan filtra zgodny / niezgodny ze stroną |
| `ctx:*` | koszty w R, spread w R, R w ATR, godzina, reżim, silnik, wynik heurystyczny / 100, relacja DXY |
| `plan:*` | kształt planu |

Wyniki o różnych znaczeniach to osobne cechy i nigdy nie są uśredniane. Brak modelu oznacza wartość 0 **i** maskę 1. Dokładnie tę politykę widzi trening, więc brak nie udaje neutralnego prawdopodobieństwa.

## Procedura (`quant/metamodel.train`)

1. **Zadanie**: wiersze jednego `task_hash` (ten sam EventSpec), posortowane według czasu decyzji.
2. **Bloki** DEV 60% → CAL 20% → TEST 20% według czasu. **Purge**: wiersz wcześniejszego bloku, którego etykieta rozstrzygnęła się po starcie następnego bloku (minus `embargo_s`), wypada.
   `assert_no_future` jest sprawdzane na każdej granicy.
3. **DEV, walk-forward**: K = 4 rozszerzające się foldy z tym samym purge. W każdym foldzie wybór cech (pokrycie ≥ 5%), skaler i model są dopasowywane tylko na części treningowej.
   Siatki: C ∈ {0,01; 0,1; 1; 10} (logistyczna L2), α ∈ {0,1; 1; 10; 100} (ridge net R). Wybór następuje według średniego OOF log loss / MAE.
4. **Ablacja na tych samych foldach**: prior → plan + kontekst → + wyniki modeli (`ablation_dev_oof`). Wariant wybiera się wyłącznie na DEV.
5. **Model końcowy** dopasowany na całym (oczyszczonym) DEV.
6. **Kalibracja na CAL**: identity / temperature / sigmoid (isotonic tylko przy n_CAL ≥ 1000) porównane na podziale „w przód” wewnątrz CAL, wybrany dopasowany na całym CAL.
   Na CAL powstają też kwantyle reszt net R.
7. **Zamrożenie, a potem jednokrotny TEST**:
   - log loss, Brier, AUC, koszyki niezawodności z licznościami, ECE vs prior;
   - MAE net R vs zero i vs średnia DEV;
   - pokrycie przedziału 80%;
   - strategia „wejście, gdy E[net R] > 0” vs „każdy kandydat” po kosztach: suma net R, expectancy (bootstrap blokowy), drawdown, odsetek wejść.

   Identyfikatory wierszy TEST trafiają do `ACTIVE.json → seen_tests`. Kolejny trening, którego TEST nachodzi na oglądany wcześniej TEST, nie może zostać promowany (`test_block_fresh`).

Test przecieku (`TestMetaModel.test_no_level_sees_future_labels`): zmiana etykiet TEST nie zmienia współczynników, kalibratora ani wyboru.

## Kryteria promocji (ustalone przed treningiem, zapisane w manifeście)

| Kryterium | Wartość |
|---|---|
| minimalne liczności DEV / CAL / TEST | 300 / 100 / 100 |
| każda klasa w TEST | ≥ 20 |
| log loss TEST < log loss prior − | 0,005 |
| ECE (10 koszyków, koszyk ≥ 10) | ≤ 0,08 |
| foldy DEV lepsze od prior | ≥ 75% |
| dane | wyłącznie REAL |
| TEST | nieoglądany wcześniej |
| głowa net R | tylko gdy net R znany w ≥ 90% wierszy |

Wartości są punktem startowym dla danych tego bota i można je zmienić w `CRITERIA` (zmiana wymaga nowego treningu). Nie są gwarancją skuteczności.

Statusy:
- `INSUFFICIENT_EVIDENCE` – brak modelu, raport dowodów;
- `VALIDATION_FAILED` – artefakt zapisany, nie da się go aktywować;
- `VALIDATED_SHADOW` – można go aktywować w SHADOW.

ASSIST wymaga osobnej, jawnej decyzji użytkownika.

## Artefakty

- Format: czysty JSON (współczynniki, skaler, kalibrator), bez pickle. Ścieżka: `<dane>/quant/models/<instrument>/<task_hash>/<wersja>/`.
- Manifest zawiera: zakresy czasowe bloków, hash danych, EventSpec, schemat cech (`PMW-QUANT-FEAT-1:<hash>`), seed, metryki, baseline, kryteria, kalibrator, próbkę odtworzenia (5 wierszy) i status.
- `load` sprawdza SHA-256, wersję, schemat cech i odtworzenie próbki (tolerancja 1e-9). Niezgodność daje `MetaError` (stan INCOMPATIBLE).
- Wskaźnik `ACTIVE.json` przechowuje historię i obsługuje `rollback`.

## Wyniki na dzień wydania 1.35.0

| Pozycja | Stan |
|---|---|
| Trening na danych rzeczywistych użytkownika | **NOT_RUN / BLOCKED_DATA** – w środowisku budowania nie ma terminala MT5 ani danych użytkownika; ledger Quant zaczyna się zbierać od pierwszego uruchomienia 1.35 w SHADOW |
| Trening na danych syntetycznych (test kodu) | PASS w testach: informatywna cecha syntetyczna daje `VALIDATED_SHADOW`, szum daje `VALIDATION_FAILED`, dane SYNTHETIC zawsze `VALIDATION_FAILED (data_real)`. To dowód działania kodu, **nie** skuteczności rynkowej |
| Trening z pustego ledgera (demo) | `INSUFFICIENT_EVIDENCE` (CLI kod 2, API zadanie DONE z tym statusem) |
| Modele bazowe | zob. `INVENTORY.md`: na czystej instalacji 0 zwalidowanych dla roli; Kronos / gold_candles / modele deep wymagają swoich środowisk; Event GRU, scalp A, lab, trainhub wymagają treningu |

## Ograniczenia

- Jeden model na `task_hash`. Rzadkie kształty planu długo nie zbiorą 500+ wierszy.
- Purge zakłada, że `resolve_ts` = zamknięcie świecy ostatniego wypełnienia albo koniec horyzontu.
- HGB/XGBoost jako challenger nie został dodany: nie ma danych pozwalających wykazać korzyść OOS.
