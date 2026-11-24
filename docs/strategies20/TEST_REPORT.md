# Raport testów – pakiet 20 strategii (1.38.0)

Środowisko: Linux (kontener), Python 3.13, Chromium (Playwright), symulator terminala MT5 (`--demo`). Brak terminala MT5 użytkownika,
brak Windows. Poniżej wyłącznie wykonane przebiegi.

## Stan bazowy przed zmianą

Pełna regresja 1.37.0 (`tools/run_tests.py`): 1289 testów, 22 pominięte, 1 błąd (oczekiwana lista migracji bez 0026) – poprawiony w 1.37.

## Testy pakietu

| Zestaw | Komenda | Wynik |
|---|---|---|
| Pakiet (katalog, jednostki, RR, 20 detektorów BUY/SELL/near-miss/rozgrzewka/brak look-ahead, rozgrzewka H1, plan i id, kontrakt dla każdego ID, polityki hedge, PAPER TP1/TP2 bez BE, przerwanie po poślizgu, koszyk z limitem po TP1 i unwind na TP2, NETTING, SIGNALS bez zleceń, arbitraż, replay, M3, STOP_FIRST) | `python -m unittest test_sh_pack` | 24 testy OK |
| UI + API (panel 20 wariantów, szczegóły, filtr Hedge, warstwa „Pakiet 20”, 400 dla złych ID/TF, M3, statystyki, GET nie otwiera planu, brak obcego symbolu) | `python -m unittest test_ui_sh_pack` | 1 test OK (Chromium, bez błędów strony) |
| Istniejące zestawy wskazane w masterprompcie: `test_sh_core`, `test_sh_service`, `test_sh_fixes`, `test_sh_risk_state`, `test_sh_setup`, `test_sh_scenario`, `test_sh_api`, `test_sh_training`, `test_finish_plan`, `test_strategies`, `test_signal_contract`, `test_signal_view`, `test_decision_arc_u6`, `test_risk_execution`, `test_quant_core`, `test_tsfm_bot`, `test_plans_svp_u3` | `python -m unittest …` | 226 testów: 1 błąd (lista migracji bez 0027) – poprawiony, powtórzony: OK |
| UI wież i warstw planów (`test_ui_pmw133`, `test_ui_towers`) | | 6 testów OK (po poprawce cyklu życia znaczników) |
| Pełna regresja | `python tools/run_tests.py` | 1314 testów, 22 pominięte (inny interpreter / sprzęt), 6 błędów z jednej przyczyny – testy architektury podstawiają `arbitrate` zwracające decyzje bez `signal_id` (stary kontrakt); dodana zgodność wstecz w serwisie, `test_arch_fixes` + `test_evaluation` powtórzone: 37/37 OK. Po ostatnich zmianach powtórzono 155 testów z dotkniętych zestawów (pakiet, UI pakietu, SH, sygnały, plany, wieże): OK |
| Frontend | `npm run typecheck`, `npm run build` | OK |
| Zadanie runnera `sh_pack` (demo: eksport → jakość → replay) | `python -m masterquo training run --profile TEST_INSTALACJI --tasks sh_pack --demo --no-detect` | UKOŃCZONE, TEST_TECHNICZNY, 38 wariantów × TF, werdykty NOT_VALIDATED |
| Replay CLI (dane syntetyczne, 40 000 M1) | `python -m masterquo sh pack-replay --dataset … --allow-synthetic` | 52 s; HG w WARMING_UP (28 dni < 42 dni rozgrzewki H1), SC z planami; werdykty NOT_VALIDATED |

## Wydajność (zmierzone)

| Pomiar | Maszyna | p50 | p95 |
|---|---|---|---|
| `PackEngine.evaluate` – 20 wariantów × 38 TF, offline (smoke, syntetyczne świece) | kontener 4 vCPU | 26 ms | 33 ms |
| ten sam cykl w działającym bocie demo (raz na zamkniętą M1; współdzielony CPU z innymi usługami) | kontener 4 vCPU | 337 ms | 738 ms |
| detektory w replayu (krok M1) | kontener 4 vCPU | ok. 1,3 ms / krok (40 000 M1 w 52 s, z symulacją planów) | – |

Jedna generacja cech na TF i cykl (wspólny `features.Context`), brak kopii modeli – pakiet czyta istniejące konteksty Kronos /
Chronos-2 / FinCast / rodzin, panel i GET nie uruchamiają inferencji ani skanu.

## Stan 20 strategii

`IMPLEMENTED` = kod detektora, planu i (HG) polityki w repozytorium; `TESTED` = testy mechaniki powyżej (dla każdego ID: BUY,
lustrzany SELL, near-miss, rozgrzewka, brak look-ahead, poziomy i strzałka planu); walidacja skuteczności – brak danych MT5 użytkownika.

| ID | Implementacja | Testy mechaniki | Walidacja skuteczności |
|---|---|---|---|
| PMW_HG01 MTF EMA Pullback / Correction Hedge | IMPLEMENTED | TESTED (+ polityka) | NOT_VALIDATED |
| PMW_HG02 Breakout–Retest / Level Failure Hedge | IMPLEMENTED | TESTED (+ polityka) | NOT_VALIDATED |
| PMW_HG03 Donchian Trend / Midchannel Hedge | IMPLEMENTED | TESTED (+ polityka: aktywacja, unwind, timeout, jedna aktywacja, SELL) | NOT_VALIDATED |
| PMW_HG04 Session Opening Range / Range Return Hedge | IMPLEMENTED | TESTED (+ polityka) | NOT_VALIDATED |
| PMW_HG05 Anchored VWAP Trend / AVWAP Loss Hedge | IMPLEMENTED | TESTED (+ polityka) | NOT_VALIDATED |
| PMW_HG06 Volatility Squeeze / Impulse Exhaustion Hedge | IMPLEMENTED | TESTED (+ polityka) | NOT_VALIDATED |
| PMW_HG07 Failed Breakout Reclaim / Reclaim Loss Hedge | IMPLEMENTED | TESTED (+ polityka) | NOT_VALIDATED |
| PMW_HG08 Value Area Rotation / Acceptance Hedge | IMPLEMENTED | TESTED (+ polityka) | NOT_VALIDATED |
| PMW_HG09 Adaptive Trend / Volatility Budget Hedge | IMPLEMENTED | TESTED (+ polityka) | NOT_VALIDATED |
| PMW_HG10 Trend Continuation / Profit Giveback Hedge | IMPLEMENTED | TESTED (+ polityka) | NOT_VALIDATED |
| PMW_SC01 EMA20 Trend Pullback | IMPLEMENTED | TESTED | NOT_VALIDATED |
| PMW_SC02 Session VWAP Reclaim–Retest | IMPLEMENTED | TESTED | NOT_VALIDATED |
| PMW_SC03 Opening Range Breakout–Retest | IMPLEMENTED | TESTED | NOT_VALIDATED |
| PMW_SC04 Donchian20 Micro Breakout | IMPLEMENTED | TESTED | NOT_VALIDATED |
| PMW_SC05 Bollinger Squeeze Breakout | IMPLEMENTED | TESTED | NOT_VALIDATED |
| PMW_SC06 Sweep / Failed Breakout Reclaim | IMPLEMENTED | TESTED | NOT_VALIDATED |
| PMW_SC07 Bollinger Range Reversion + RSI | IMPLEMENTED | TESTED | NOT_VALIDATED |
| PMW_SC08 Stochastic Trend Pullback | IMPLEMENTED | TESTED | NOT_VALIDATED |
| PMW_SC09 MACD Momentum Reset | IMPLEMENTED | TESTED | NOT_VALIDATED |
| PMW_SC10 Session Value Area Rejection | IMPLEMENTED | TESTED | NOT_VALIDATED |

Polityki HG01–HG10: dla wszystkich sprawdzono teksty warunków i ograniczenie straty scenariuszowej; pełny scenariusz decyzji
(aktywacja → unwind → timeout, lustro SELL) – HG03; pozostałe polityki są wykonywane w replayu (`replay.simulate`) na tych samych
funkcjach. Przepływ koszyka w serwisie (hedge PAPER, limit po TP1, unwind na TP2, NETTING) sprawdzony na HG03 z polityką podstawioną
w teście.

## Nie wykonano (z powodem)

* Walidacja OOS na historii MT5 użytkownika – brak danych (wynik: NOT_VALIDATED dla wszystkich 20).
* Test na Windows i z prawdziwym terminalem MT5 (AUTO_DEMO / AUTO_LIVE) – brak w środowisku.
* DSR / PBO – wymagają realnych serii wyników wielu konfiguracji; raport replayu wymienia wszystkie próby.
