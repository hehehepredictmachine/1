# VALIDATION_PROTOCOL – MQ-LAB-VAL-1.0.0 (zamrożony przed badaniem)

Implementacja: `backend/masterquo/lab/protocol.py`.
- Protokół jest słownikiem z hashem `protocol_id` (`VP-…`), zapisywanym przy każdej próbie (`lab_trials`).
- Zmiana któregokolwiek parametru daje nowy `protocol_id`.

## 1. Pytanie i etykiety (osobno dla każdego aktywa i horyzontu)

**Pytanie:**
- Decyzja zapada przy zamknięciu świecy M5 *i*.
- Wejście LONG (lub SHORT) po otwarciu świecy *i+1* (najwcześniejszy fill), z uwzględnieniem spreadu.
- Pytamy: czy TP = 1,5×ATR14 zostanie osiągnięty przed SL = 1,0×ATR14 w ciągu H = 12 świec?

**Zasady etykiet (LBL-TB-1.0.0):**
- To nie jest pytanie o kierunek następnej świecy.
- Strona bid/ask:
  - LONG: wejście po Ask, wyjście po Bid;
  - SHORT: wejście po Bid, wyjście po Ask.
- Jeśli SL i TP padają w tej samej świecy OHLC, przyjmujemy najpierw SL (wariant konserwatywny). Takie przypadki są liczone i raportowane.
- Etykieta niedojrzała do daty odcięcia jest usuwana, a nie zgadywana.
- Luka większa niż (H+3)×TF w oknie etykiety usuwa próbkę.
- Timeout = klasa 0; wynik w R z zamknięcia.
- Abstencja jest stanem silnika: brak transakcji, gdy p < `p_trade` (0,55).

## 2. Podziały

1. **Holdout:**
   - chronologicznie ostatnie 20% zdarzeń;
   - dev zawiera tylko próbki, których etykieta kończy się przed początkiem holdoutu (purging);
   - holdout zaczyna się po embargo równym H świec;
   - hash czasów holdoutu jest zapisywany.
2. **Walk-forward:**
   - ekspandujący, 4 foldy na dev;
   - trening = próbki, których koniec etykiety < początek walidacji − embargo.
3. **Strojenie** wewnątrz foldu: ostatnie 25% treningu (chronologicznie). Budżet: 3 konfiguracje na rodzinę.
4. **Dopasowanie wyłącznie w treningu:** scaler, PCA, GMM (syntetyczne wiersze tylko w treningu), neutralizacja, biasy MiniRocket, normalizacja sekwencji, early stopping.
5. **Seedy:** stały zestaw {11, 23, 37}. Predykcje są uśrednione po seedach, bez wyboru „szczęśliwego” seeda.

## 3. Rodziny

| Rodzaj | Rodziny |
|---|---|
| bazowe | DUMMY (stopa bazowa), RULE (ema_gap_50 > 0) |
| proste modele | LOGREG (L2), TREE |
| sekwencyjne | MINIROCKET + regresja logistyczna, RESNET1D, SEW_SNN (z routingiem wg reżimu) |
| challenger | XGB |
| eksperymenty | LOGREG_PCA, LOGREG_GMM_AUG, LOGREG_NEUTRALIZED |

**Nie budowano:**
- ensemble ani meta-modelu – nie ma kandydatów z przyrostową wartością;
- CatBoost – nie jest zainstalowany.

## 4. Metryki

Liczone per fold:
- liczba zdarzeń, stopa bazowa;
- log loss, Brier, ECE (10 koszy), AUC;
- transakcje, pokrycie, abstencje;
- expectancy w R, win rate, maksymalne obsunięcie w R.

Agregacja: średnia ± odchylenie po foldach.

## 5. Kontrole negatywne

| Kontrola | Opis |
|---|---|
| PERMUTED_BLOCK_LABELS | etykiety mieszane blokami po 50 |
| FUTURE_SHIFTED_LABELS | etykieta wiersza i+10H, z purgingiem granic |

Zysk log loss nad DUMMY w którejkolwiek kontroli powyżej progu → werdykt `NO_VALIDATED_EDGE` z powodem „możliwy przeciek – wymaga dochodzenia”.

## 6. Kryteria promocji (ustalone przed testem)

- Log loss lepszy od DUMMY o ≥ 0,002 w ≥ 75% foldów.
- ECE ≤ 0,10.
- Liczba transakcji OOF ≥ max(60, min_events/10). Liczba wynika z liczby zdarzeń – nie ma jednej uniwersalnej wartości.
- 95% CI średniej R (bootstrap blokowy, po koszcie stresowym 0,10 R) > 0.

Kandydat wybierany jest **wyłącznie na dev**. Holdout sprawdzany jest **raz** dla zamrożonego kandydata:
- dostęp zapisany w `lab_holdout_access`;
- drugie użycie → `HOLDOUT_ALREADY_USED`.

Brak danych → `INSUFFICIENT_EVIDENCE`. Brak przewagi → `NO_VALIDATED_EDGE`. Progi nie są obniżane po wyniku.

## 7. Po kwalifikacji

**Role artefaktu:**

| Rola | Kiedy |
|---|---|
| `fixture_only` | dane syntetyczne – nigdy nie wpływa na decyzje |
| `research` | dane MT5, brak zaliczonego holdoutu |
| `shadow` | zaliczony holdout |

Promocja do „active” nie jest zaimplementowana automatycznie. Wymaga shadow/paper na nowych danych i decyzji użytkownika.

**Retrening** tworzy challengera, nie podmienia championa.

**Ograniczenia:**
- DSR/PBO nie są liczone, bo brak wielu niezależnych strategii na danych rynkowych.
- Selection bias ograniczają: budżet prób, rejestr wszystkich prób i jednorazowy holdout.
