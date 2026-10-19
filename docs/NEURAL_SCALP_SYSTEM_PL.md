# Neural Scalp System (PMW-UPD-04) – CAUSAL_MTF_TCN_V1 / SCALP_SETUP_MARKET_V1

## Co to jest
Mała przyczynowa sieć TCN (NumPy, bez PyTorch/GPU), która ocenia **konkretnego kandydata** strategii Range → Sweep/Reclaim → Retest
(scalp, wejście MARKET). Nie zastępuje strategii i nie wysyła zleceń.

| Element | Konfiguracja (zamrożona, `lab/scalp_net.py::DEFAULT_CFG`) |
|---|---|
| Gałąź M1 | 128 zamkniętych M1 × 8 kanałów → stem 1×1 (16) → 5 bloków rezydualnych k=3, dylatacje 1,2,4,8,16 (pole recepcyjne 125) |
| Gałąź M5 | 32 zamknięte M5 → stem (16) → 3 bloki, dylatacje 1,2,4 (pole recepcyjne 29) |
| Kontekst | ostatnie zamknięte M15/H1 (5 cech każdy) + `SETUP_FEATURES` → dense 32 → 16 |
| Fuzja | 16 + 16 + 16 = 48 → 32 (ReLU) |
| Głowice | osobno LONG i SHORT: 3 logity (TP1_FIRST, SL_FIRST, TIMEOUT) + net_R (MSE = średnia warunkowa) |
| Trening | Adam lr 0.001, batch 64, ≤60 epok, patience 7 na INNER_TUNE, L2 1e-4, clipping normy 1.0; ensemble seedów 17/29/43 |
| Rozmiar | ok. 16 tys. parametrów na członka, ok. 1,15 mln MAC na inferencję (rzeczywiste liczby w panelu i manifeście) |

Blok: `ReLU(x + conv_d(ReLU(conv_d(x))))`, lewy padding `(k-1)·d` – każde wyjście zależy wyłącznie od przeszłości (test przyczynowości i
pola recepcyjnego w `tests/test_nss.py`). Gradienty sprawdzone numerycznie.

## Znaczenie wyniku
* `P(TP1_FIRST)`, `P(SL_FIRST)`, `P(TIMEOUT)` – pierwsze wyjście cyklu w czasie `max_hold` profilu; sumują się do 1 tylko w obrębie jednej strony.
  P(TP1 przed SL) **nie jest** prawdopodobieństwem zysku całej pozycji.
* `expected_net_R` – estymata wyniku całego cyklu (TP1/TP2, BE, wyjście czasowe, prowizja, poślizg) w R; nie gwarantowany zarobek.
* Inne pierwsze wyjście → `EARLY_EXIT` (wykluczone i policzone). Brak wykonalnego wejścia → `NO_EXECUTABLE_ENTRY`, nie klasa TIMEOUT.
* Panel rozróżnia „Wynik surowy modelu” i „Po kalibracji” (temperature scaling per strona na CALIBRATION).

## Dane i czas
`lab/nss.py::snapshot` – jedna funkcja dla treningu, replayu i live: tylko świece z `open + TF ≤ T`, okno + 20 świec rozgrzewki, jednostka =
ATR okna. Luka > 90 min, duplikat, zerowy ATR, brak spreadu albo brak cechy setupu → `DATA_GAP` / `INVALID_FEATURES` / `WARMING_UP`
(nigdy zera). Historia: `availability_basis = HISTORICAL_CLOSE_ASSUMPTION`, precyzja `OHLC_APPROX`.

## Protokół (wspólny z PMW-UPD-03)
Holdout = ostatnie 20 % kalendarza, rezerwowany we wspólnym `eval_ledger` przed odczytem (ponowne użycie → REUSED_PERIOD_EXPLORATORY);
4 rozszerzające się foldy; FIT 60 / INNER_TUNE 15 / CALIBRATION 15 / POLICY 10 z purge + embargo; baseline: rozkład klas, regresja
logistyczna, Ridge, ResNet1D (istniejący lab, to samo zadanie), Task B = NOT_COMPARABLE. Polityka (siatka P(TP1) 0.45/0.55/0.65 ×
net_R 0/0.05/0.10) tylko na POLICY. Finalny ensemble jest zapisywany (NPZ `allow_pickle=False` + manifest z sha256), odczytywany
loaderem runtime i dopiero on jest oceniany raz na holdoucie. Kryteria: `lab/nss.py::CRITERIA` (m.in. ≥1000 kandydatów strony w
FIT+TUNE, ECE ≤ 0.10, ≥100 cykli i ≥30 dni polityki, CI95 > 0 i przyrost CI95 > 0, stres kosztów, DD ≤ 15 R). Budżet 120 min →
`BUDGET_EXCEEDED`.

## Runtime
`lab/nss_service.py`: własny zegar M1 (niezależny od M5 w lab), wątek roboczy, kolejka maks. 8, timeout 2 s, odrzucanie odpowiedzi
starej sesji/aktywa. Kandydat ze `ScalpService` trafia jako zamrożona kopia przed jakimkolwiek filtrem modelu. Rekord
`nss_inferences` (migracja 0018) jest zapisywany **przed** zdarzeniem WS `lab_neural`; etykieta dopisywana później (`settle`).
Bez kandydata: tylko telemetria enkoderów (`CONTEXT_ONLY`), bez prawdopodobieństwa.

Role: domyślnie OBSERVE; SHADOW_GATE (hipotetyczny filtr) tylko dla strony z HOLDOUT_PASSED. Żadna rola nie zmienia bramek scalp,
ryzyka, wielkości pozycji ani Execution Lock. Wybór i rollback są ręczne.

## Obsługa
* Panel: Pulpit → karta „Neural System — Scalping”; Modele i trening → **Neural System** (`#/neural`): Przepływ i warstwy, Aktywacje,
  Setup, Trening i walidacja, Historia i zdrowie; przyciski Sprawdź gotowość / Przygotuj dane / Trenuj kandydata / Anuluj / Otwórz raport /
  Wybierz model do obserwacji / Przywróć poprzedni.
* `23_NEURAL_SCALP.bat` (menu) albo `python -m masterquo neural-scalp doctor|prepare|train|status|report|rollback|select --asset XAUUSD`.
* API: `GET /api/v1/lab/neural`, `/history`, `/report`, `/jobs`; `POST /api/v1/lab/neural/{doctor,prepare,train,cancel,select,rollback}`;
  `POST /api/v1/lab/train` z `task_id=SCALP_SETUP_MARKET_V1`. Zadanie `neural_scalp` w runnerze treningu (13 zadań na instrument).
* BTC: osobny profil scalp (`config/scalp_profile_BTC_v1.json`) i osobne artefakty; wagi/skalowanie XAUUSD nigdy nie są używane dla BTC.

## Stan
Kod, integracja i testy na danych generowanych: gotowe. Trening na danych użytkownika: NOT_RUN (brak eksportu MT5 w środowisku
budowy) – `BLOCKED_NO_REAL_DATA`. Przewaga: NOT_EVALUATED. Opóźnienia p95 na docelowym CPU: do zmierzenia lokalnie (panel → Historia i zdrowie).

## Rollback
Przycisk „Przywróć poprzedni” / `neural-scalp rollback` przywraca poprzedni wybór całego bundla. Usunięcie katalogu `data/nss/<INSTR>`
wyłącza NSS (stan NO_MODEL) bez wpływu na inne moduły.
