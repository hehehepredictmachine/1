# PMW-SH-1 · Etap 3 – Rejestr modeli, role i wspólna analiza

Źródło prawdy w kodzie: `backend/masterquo/sh/models.py` (`REGISTRY`, `probe`, `participation`, `matrix`).
Status każdego wpisu pochodzi z **sondy na żywo**: pliku rejestru, aktywnego wskaźnika, tpmodel.status lub serwisu w runtime.
Statusy nie są deklarowane w dokumentacji. Tabela poniżej pochodzi z uruchomienia `matrix(None, "XAUUSD")` na pustym katalogu
danych, czyli jest stanem „świeża instalacja, bez treningu”. U klienta status zależy od jego katalogu `data/`.

## Zasady udziału w decyzji

| Rola | Udział, gdy komponent jest gotowy | Udział, gdy nie jest |
|---|---|---|
| DATA_QUALITY, RISK_ANOMALY, REGIME | **GATE**: musi przejść, inaczej WAIT/NO_TRADE | GATE_UNAVAILABLE, czyli WAIT z powodem |
| TARGET_PROB | **PROBABILITY**: jedyne źródło prawdopodobieństwa, wyłącznie dla zdarzenia strategii | NONE; setup ma tylko score, a tryb jest OGRANICZONY |
| DIRECTION_STRUCTURE, TIMING, VOLATILITY, PATTERN, LIQUIDITY | EVIDENCE (raz na grupę korelacji) | INFO (SHADOW) albo NONE |
| SUPERVISION | INFO, nigdy głos | – |

* **Grupa korelacji = jeden dowód.** Przykład: scalp_A, si_move i flow_reaction przewidują kierunek M1 (`M1_DIRECTION`).
  Ich zgodność nie jest trzema niezależnymi potwierdzeniami.
* **Prawdopodobieństwo vs score.** Tylko `sh_tp_model` jest trenowany na dokładnie zdarzeniu strategii, czyli „TP2 przed SL w
  horyzoncie H min” przy siatce TP danej strategii. Pozostałe modele przewidują inne zdarzenia: TP1 setupu Range→Sweep, barierę
  1.5 ATR, net-R > 0 albo kierunek zamknięcia świecy. Ich wynik jest pokazywany jako **score** z opisem zdarzenia, nigdy jako
  prawdopodobieństwo TP strategii.
* **Model nieprzetrenowany, niezgodny (hash lub schemat cech) albo bez ścieżki inferencji na żywo** (F-17: context_move,
  reaction models) nigdy nie jest źródłem decyzji.

## Tryb pracy

* **PEŁNA**: `sh_tp_model` w statusie READY dla instrumentu i strategii (bramka holdout zaliczona). Setup READY wymaga
  wtedy dodatkowo P ≥ `tp_model_min_prob`.
* **OGRANICZONA** (zdefiniowana, domyślna po instalacji): setup działa na deterministycznej analizie i ma tylko score. Sygnały
  idą wyłącznie do SIGNALS lub PAPER; **AUTO jest zablokowane**. To nie jest awaria, tylko stan przewidziany na brak modelu.

## Macierz model × strategia × rola (świeża instalacja)

| id | rodzaj | grupa korelacji | SCALPING | HEDGING | trening | status (sonda) |
|---|---|---|---|---|---|---|
| data_quality | DETERMINISTIC | DATA | DATA_QUALITY | DATA_QUALITY | nie wymaga treningu | DATA_MISSING (brak runtime) |
| risk_engine | DETERMINISTIC | RISK | RISK_ANOMALY | RISK_ANOMALY | nie wymaga treningu | DETERMINISTIC_OK |
| news | DETERMINISTIC | RISK | RISK_ANOMALY | RISK_ANOMALY | nie wymaga treningu | DETERMINISTIC_OK |
| regime_v2 | DETERMINISTIC | REGIME | REGIME | REGIME | nie wymaga treningu | DETERMINISTIC_OK |
| structure_v2 | DETERMINISTIC | STRUCTURE | DIRECTION_STRUCTURE | DIRECTION_STRUCTURE | nie wymaga treningu | DETERMINISTIC_OK |
| smc_pullback | DETERMINISTIC | STRUCTURE | DIRECTION_STRUCTURE | DIRECTION_STRUCTURE | nie wymaga treningu | DETERMINISTIC_OK |
| vamd | DETERMINISTIC | MOMENTUM | TIMING | TIMING | nie wymaga treningu | DETERMINISTIC_OK |
| fractal | DETERMINISTIC | REGIME | REGIME | REGIME | nie wymaga treningu | DETERMINISTIC_OK |
| atr_vol | DETERMINISTIC | VOLATILITY | VOLATILITY | VOLATILITY | nie wymaga treningu | DETERMINISTIC_OK |
| candles_patterns | DETERMINISTIC | PATTERN | PATTERN | PATTERN | nie wymaga treningu | DETERMINISTIC_OK |
| liquidity | DETERMINISTIC | LIQUIDITY | LIQUIDITY | LIQUIDITY | nie wymaga treningu | DETERMINISTIC_OK |
| flow_sr | DETERMINISTIC | STRUCTURE | DIRECTION_STRUCTURE | LIQUIDITY | nie wymaga treningu | DETERMINISTIC_OK |
| decomposition | DETERMINISTIC | CYCLE | SUPERVISION | SUPERVISION | nie wymaga treningu | DETERMINISTIC_OK |
| **sh_tp_model** | TRAINED | TP_EVENT_SH | **TARGET_PROB** | **TARGET_PROB** | sh_models | NOT_TRAINED |
| scalp_A | TRAINED | M1_DIRECTION | DIRECTION_STRUCTURE | TIMING | scalp_A | NOT_TRAINED |
| scalp_B | TRAINED | TP_OTHER_EVENT | SUPERVISION | SUPERVISION | scalp_A | NOT_TRAINED |
| gold_forecast | TRAINED | M5_DIRECTION | TIMING | DIRECTION_STRUCTURE | forecast | NOT_TRAINED |
| legacy_ml | TRAINED | TP_OTHER_EVENT | SUPERVISION | SUPERVISION | ml | UNAVAILABLE bez runtime |
| lab | TRAINED | TP_OTHER_EVENT | SUPERVISION | SUPERVISION | lab | NOT_TRAINED |
| indicator_context | TRAINED | TP_OTHER_EVENT | SUPERVISION | SUPERVISION | indicator_context | NOT_TRAINED |
| ml_scalp | TRAINED | TP_OTHER_EVENT | SUPERVISION | SUPERVISION | ml_scalp | NOT_TRAINED |
| nss | TRAINED | TP_OTHER_EVENT | SUPERVISION | SUPERVISION | neural_scalp | NOT_TRAINED |
| si_move | TRAINED | M1_DIRECTION | DIRECTION_STRUCTURE | TIMING | structure_intelligence | NOT_TRAINED |
| flow_reaction | TRAINED | M1_DIRECTION | TIMING | TIMING | flow_context | NOT_TRAINED |
| context_move | TRAINED | M5_DIRECTION | TIMING | DIRECTION_STRUCTURE | context_indicators | NOT_CONNECTED (F-17) |
| agent | EXTERNAL | AGENT | SUPERVISION | SUPERVISION | nie wymaga treningu | SHADOW_ONLY |

## Wspólna analiza (`sh/context.py`)

* Analiza liczy się wyłącznie z **zamkniętych** świec. Świeca w trakcie tworzenia jest odrzucana i raportowana.
* Każdy komponent dostaje osobny status OK, WARMUP albo ERROR. Błąd jednego komponentu nie ukrywa pozostałych.
* Data quality sprawdza:
  * kolejność i duplikaty świec;
  * wartości NaN i inf;
  * geometrię OHLC;
  * wiek ostatniej świecy na każdym interwale;
  * wiek notowania;
  * relację Ask ≥ Bid;
  * spread względem limitu instrumentu.
* Snapshot jest liczony raz i współdzielony przez SCALPING i HEDGING. Obie strategie widzą ten sam reżim i tę samą strukturę.
  Rozbieżność między nimi może więc wynikać tylko z ich reguł, nie z różnych danych.

## Model zdarzenia `sh_tp_model` (`sh/tpmodel.py`)

* Etykieta: TP2 osiągnięty przed SL w horyzoncie strategii. Etykiety pochodzą z replay **własnych setupów strategii** (te same
  automaty stanów co na żywo, patrz etap 9) z konserwatywnym rozstrzyganiem świec niejednoznacznych.
* Podział danych:
  * chronologicznie 60 % fit / 20 % kalibracja / 20 % holdout;
  * embargo między blokami;
  * skaler i regresja logistyczna uczone tylko na bloku fit;
  * kalibracja Platta tylko na bloku kalibracji;
  * holdout używany raz.
* **Bramka promocji**: Brier holdoutu lepszy od stopy bazowej o więcej niż 2 SE różnicy sparowanej oraz minimalna liczba
  próbek. Test `test_sh_setup.TpModel` pokazał, że sama nierówność „Brier < bazowy” przepuszczała model z czystego szumu.
  Bramkę poprawiono.
* Plik `.npz` (bez pickle) zapisywany jest z sha256. Predykcja odmawia przy niezgodnym hashu lub schemacie cech
  (INCOMPATIBLE). Promocja zmienia wskaźnik `active` atomowo, każdy run jest zachowany, a rollback przywraca poprzedni model.

## Analiza ablacyjna i korelacji błędów – plan i status

Analiza wymaga przetrenowanych modeli i zbioru setupów z replay na danych klienta. W tym środowisku nie ma eksportu historii
XAUUSD- ani BTC z terminala, więc **analiza nie została wykonana (BLOKER B-DATA, patrz lista blokerów)**. Procedura jest
zaimplementowana w raporcie walidacji (etap 9):

1. Dla każdego setupu z replay zapisuje się predykcje modeli z grupami korelacji READY/SHADOW.
2. Liczona jest korelacja Spearmana błędów (y − p) między modelami. Grupa z korelacją > 0.6 liczy się jako jeden dowód.
3. Ablacja polega na porównaniu wyniku netto i Brier dla: setup bez modelu, setup + `sh_tp_model`, setup + score innych
   modeli jako cecha. Model nie wnoszący poprawy poza 2 SE pozostaje INFO.

## Etap 3 – raport

* **Zmieniono/dodano:**
  * pliki `sh/models.py`, `sh/context.py`, `sh/config.py`, `sh/setup.py`, `sh/tpmodel.py`;
  * konfiguracja `config/sh_strategies_v1.json`;
  * testy `tests/test_sh_setup.py` (16).
* **Sprawdzono:**
  * przeszło 16/16 testów: config validate/override/rollback, BUY/SELL READY z TP od Ask/Bid na siatce ticków, WAIT przy
    konflikcie interwałów i braku triggera, NO_TRADE dla nieaktualnych danych, przeszkody, za szerokiego SL, zablokowanego
    BTC i waluty innej niż USD, INVALIDATED, odwrócenie w zakresie, model zdarzenia (bramka, promocja, predykcja,
    integralność, rollback);
  * smoke test snapshotu na rzeczywistych modułach analizy.
* **Zablokowane:**
  * trening `sh_tp_model` i ablacja wymagają historii M1/M5/M15/H1 z terminala klienta;
  * prowizja XAUUSD-/BTC nieznana (`commission_per_lot_side: null`). AUTO wymaga jej uzupełnienia.
