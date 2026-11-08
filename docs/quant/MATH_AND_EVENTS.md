# Matematyka, jednostki i zdarzenia – PMW Quant Core

## Jednostki (`quant/units.py`)

- Ceny i wolumen wynikają ze specyfikacji brokera (`symbol_info`: `point`, `trade_tick_size`, `trade_tick_value`, `volume_min/step/max`).
- `quantize_price` zaokrągla cenę do ticka brokera.
- `quantize_volume` zaokrągla wolumen **w dół** do kroku. Wolumen poniżej `volume_min` daje `None`, nigdy zaokrąglenie w górę.
- „Pip” istnieje tylko wtedy, gdy specyfikacja podaje `pip_size`. Inaczej `PIP_UNDEFINED_IN_SPEC`.
- Pieniądze: `ruch_ceny / tick_size × tick_value × loty`, tylko gdy `tick_value` jest w walucie rachunku. Inaczej `CURRENCY_CONVERSION_UNKNOWN`.
  Ruch 2,5 USD ceny nie jest zyskiem 2,5 USD na rachunku (test `test_unknown_commission_or_currency_is_not_validated`).
- **R** to `|entry − SL|` po stronie wykonania, ustalane raz przy decyzji. Nie jest redefiniowane po przesunięciu SL na BE.

## Koszty

`CostModel.basis()` zapisuje pochodzenie kosztów:
- **spread** w cenach bid/ask (`spread_in_prices=True`) nie jest odejmowany ponownie;
- **prowizja** na lot na stronę: znana albo `None` (nieznana);
- **poślizg** w tickach na wypełnienie;
- **swap / finansowanie**: znany albo `None`.

Nieznany składnik daje status `PARTIAL`. Wynik netto jest wtedy scenariuszowy (`SCENARIO_UNKNOWN_COSTS`), nigdy `NET_VALIDATED`, i nie uczestniczy w bramce ASSIST (`QuantService.assess`: brak `would_hold`, gdy koszt nieznany).
Nazwa rachunku („Zero”) nie dowodzi kosztu zero.

## EV

```text
plan binarny (jeden cel, bez partiali/BE/timeoutu):  EV = p·G − (1 − p)·L ;  p* = L / (G + L)     (G, L > 0, netto, w R)
rozłączne, kompletne scenariusze:                    EV_net = Σ_k P_k · E[net R | k]              (Σ P_k = 1 ± 1e-6, bez cichej renormalizacji)
```

Test ręczny: G = 2R, L = 1R, p = 0,6 daje EV = 0,8R oraz p* = 1/3 (`test_hand_computable_ev`). To test wzoru, nie założenie skuteczności.

Samo P(TP2 przed SL) nie jest rozkładem wypłat planu z partialami, więc `ev_for_plan` zwraca wtedy `EV_NEEDS_SCENARIOS`.
Meta-model podaje osobno P(nazwanego zdarzenia) oraz E[net R] z modelu regresji na etykietach **netto**. Koszty są więc odjęte raz, w etykiecie.
Stare EV binarne z `evaluation/engine.py` pozostaje wyraźnie oznaczonym wynikiem porównawczym (`BINARY_PLAN_APPROX`).

## EventSpec (`quant/events.py`)

Pola specyfikacji:
- instrument, strategia, kierunek, zasada wejścia, Entry, SL;
- cele z wagami partiali (suma = 1);
- `be_after` (domyślnie TP2 dla planów SH, zgodnie z regułą BE po **potwierdzonym** TP2, aktywną od **następnej** świecy);
- `be_offset_price` (koszty), horyzont, reguła timeoutu;
- koszt round-trip i jego podstawa;
- polityka świecy niejednoznacznej;
- `event_id`, czyli zdarzenie głowy prawdopodobieństwa, np. `TP2_BEFORE_STOP`;
- `label_version` (`QEV1`).

`task_hash` opisuje kształt zadania: cele w R, wagi, BE, horyzont, politykę i zdarzenie. Zmiana planu tworzy nowe zadanie i nową wersję etykiety (`test_short_exits_on_ask_and_unknown_costs`).

### Symulator / etykieta

- Używane są tylko świece otwarte w chwili decyzji lub później i zamknięte przed końcem horyzontu.
- LONG wychodzi po bid (ceny świec MT5). SHORT wychodzi po ask, czyli bid + spread świecy. Nieznany spread jest raportowany (`spread_known=false`).
- **Luka przez stop** na otwarciu: wypełnienie po cenie otwarcia (gorszej od SL), flaga `gap`. Luka przez cel: wypełnienie po cenie celu (konserwatywnie dla zlecenia limit).
- **TP i SL w jednej świecy**: polityka ustalona przed etykietowaniem.
  - `SL_FIRST` (domyślna, konserwatywna);
  - `TP_FIRST`;
  - `BOUNDS`: etykieta wg `SL_FIRST`, a wynik `TP_FIRST` jako górna granica `net_r_bounds`.
- Koszt odejmowany jest **raz** dla całej pozycji. Partiale go nie mnożą.
- Horyzont jeszcze trwa → `mature=false`. To nie jest strata ani timeout. Rynek zamknięty po upływie horyzontu → `NO_BARS` (wynik nieznany).
- Scenariusze są rozłączne i kompletne: `TP{k}_{SL|BE|TIMEOUT|ALL}`.
- Zdarzenia: `TP{k}_BEFORE_STOP` dla każdego k, `SL_FIRST`, `TIMEOUT`, `NET_R_POSITIVE`.
  P(TP1) i P(TP2) dotyczą tej samej ścieżki i nie sumują się do 1 z innymi zdarzeniami.

## Rdzeń numeryczny (`quant/numeric.py`)

Wszystko w float64. Błędy mają nazwę: `ZERO_VARIANCE`, `SMALL_SAMPLE`, `NON_FINITE_INPUT`, `GARCH_PARAMS_NOT_STATIONARY`, `SCENARIOS_NOT_COMPLETE` …
Nie ma końcowego `nan_to_num()`.

| Obszar | Funkcje | Uwagi |
|---|---|---|
| zwroty / statystyki | `simple_returns`, `log_returns`, `rolling_mean_var` (Welford z usuwaniem), `quantiles` | stabilne dla cen ~2000 (test vs NumPy) |
| zmienność | `hist_vol`, `ewma_vol` (RiskMetrics), `garch11_forecast` (podane parametry, suma wariancji po krokach), `to_decimal`, `sqrt_time` (tylko jawnie) | bez automatycznego skalowania pierwiastkiem czasu |
| kowariancja | `align` (wspólne znaczniki, bez forward fill), `covariance` (n ≥ 5·k, kurczenie do przekątnej, naprawa PSD), `psd_repair` | raportuje liczbę obciętych wartości własnych |
| prawdopodobieństwa | `logsumexp`, `softmax`, `sigmoid`, `logit` (jawne obcięcie argumentu logarytmu), `log_loss`, `brier`, `reliability` (koszyki z licznościami, ECE), `auc` | |
| regresja / ryzyko | `regression_metrics`, `max_drawdown`, `block_bootstrap` (moving block, percentyle) | dla zależnych szeregów |

## Niepewność

- **1.33 (błąd):** `evaluation/engine.py` liczył przedział Wilsona 90% z prognozowanego p i globalnego `n_calibration`. To nie jest niepewność indywidualnego p(x).
  W 1.35 (PMW-EVAL-ENGINE-2) przedział powstaje tylko z dostarczonej, zwalidowanej metody. W pozostałych przypadkach jest `null` z przyczyną.
  Decyzja SHADOW jest wtedy `REDUCE / EV_INTERVAL_UNKNOWN` (test `test_wilson_is_not_a_model_interval`).
  `wilson()` pozostaje dla częstości empirycznych (tablica kalibracji dojrzałych wyników).
- **Meta-model** rozdziela trzy rodzaje niepewności:
  - **rozrzut przyszłego wyniku**: kwantyle 10/90% reszt E[net R] na bloku CAL; pokrycie zmierzone na TEST;
  - **niepewność parametru**: `null` z przyczyną (brak zwalidowanej metody);
  - **metryki strategii**: przedziały z bootstrapu blokowego.
- **Monte Carlo** jest oznaczane `MODEL_SIMULATED`. To nie jest prawdopodobieństwo skalibrowane na zdarzeniach.
  Liczba ścieżek zmniejsza błąd próbkowania, nie błąd modelu.
- **Kronos** to pojedyncza ścieżka ceny (REGRESSION, jednostka cena), nie prawdopodobieństwo bariery. **GPR** to rozkład terminalny log-zwrotu, nie P(TP przed SL).
  **RL** podaje akcję, nie p(win). **HDC** daje margines, nie prawdopodobieństwo.
