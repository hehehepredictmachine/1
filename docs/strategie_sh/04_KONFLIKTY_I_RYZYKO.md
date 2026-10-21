# PMW-SH-1 · Etap 4 – Macierz konfliktów, wspólny silnik ryzyka i zarządzanie stanem

Kod:
* `sh/risk.py`: wspólny silnik ryzyka;
* `sh/coordinator.py`: koordynator konfliktów;
* `sh/store.py` i migracja `0023_sh_strategies.sql`: stan, idempotencja i właściciel pozycji;
* `sh/executor.py`: wykonanie zgodne z trybem i Execution Lock.

Testy: `tests/test_sh_risk_state.py` (14).

## Macierz konfliktów

| Konflikt | Rozstrzygnięcie | Gdzie |
|---|---|---|
| BUY vs SELL w tym samym cyklu (obie strategie READY) | obie **WAIT**: „przeciwne kierunki w tym samym cyklu” | coordinator reguła 3 |
| SCALPING vs HEDGING, ten sam kierunek | wykonuje się strategia z wyższym `priority` (domyślnie HEDGING), druga **WAIT** | coordinator reguła 4 |
| Otwarty koszyk HEDGING, nowy SCALPING na symbolu | **WAIT**, nawet przy `allow_parallel_same_symbol=true`. Dwóch zarządców tej samej ekspozycji jest niedopuszczalnych. | coordinator reguła 2 |
| Otwarty plan SH, nowy plan w przeciwnym kierunku | **WAIT**: taki plan byłby niezarządzanym hedge | coordinator reguła 2 |
| Pozycja innego menedżera na symbolu (stary bot, ręczna, inny magic) | **WAIT** i blok `foreign_owner` w ryzyku: jeden właściciel pozycji | coordinator reguła 1, risk |
| Interwały sprzeczne (H1/M15 przeciw trendowi M5) | **WAIT** | setup krok 2 |
| Trend vs mean-reversion | reżim wybiera **jeden** tryb: TREND → CONTINUATION, RANGE → REVERSAL na krawędzi zakresu, środek zakresu → WAIT, TRANSITION wymaga zgodności M5 i M15. Nigdy oba tryby naraz. | setup krok 2–3 |
| Modele sprzeczne | o setupie decydują bramki deterministyczne. Prawdopodobieństwo pochodzi tylko z modelu zdarzenia READY. Modele SHADOW mają rolę INFO bez głosu. Grupa korelacji liczy się jako jeden dowód. | models.participation |
| SL/TP/trailing/BE/partiale z różnych źródeł | jeden plan zamrożony z hashem konfiguracji. SL nigdy się nie poszerza. BE wyłącznie po **potwierdzonym** TP2. Brak trailingu w SH. Legacy manager nie dotyka SH, bo SH ma własny magic 41082100. | lifecycle, executor |
| Konfiguracja globalna vs profil | jedno źródło: `config/sh_strategies_v1.json` plus override z panelu z historią. Plan zamraża parametry. Zmiana ustawień nie modyfikuje otwartej pozycji. | sh/config.py |
| Trening w trakcie inferencji | inferencja czyta tylko aktywny wskaźnik rejestru, który jest podmieniany atomowo (`os.replace`). Trening zapisuje nowy plik runu i nigdy nie nadpisuje modelu w użyciu. Hash jest weryfikowany przy predykcji. | tpmodel |
| Nieaktualny sygnał | TTL `setup_ttl_minutes` → EXPIRED (`store.expire_signals`), a risk blokuje `not_expired`. Dane starsze niż limit dają NO_TRADE. | store, risk, context |
| Wielu menedżerów pozycji | tabela `sh_owners` (PRIMARY KEY konto+ticket) i sprawdzenie właściciela przed każdą akcją na terminalu | store.own, executor |
| Ponowienia (retry) | `sh_actions` z deterministycznym `action_id`. Wynik DONE jest odtwarzany bez wysyłki. Akcja SENT/UNKNOWN nigdy nie jest wysyłana ponownie (decyduje rekonsyliacja). Akcję REJECTED można jawnie ponowić z licznikiem prób. | store.claim_action |
| Nierozstrzygnięte | **WAIT** albo **NO_TRADE** z powodem, nigdy domysł | wszędzie |

## Wspólny silnik ryzyka – limity

Zasada nadrzędna: ryzyko i dane mają pierwszeństwo przed sygnałem modelu. BLOCK nie może zostać nadpisany score ani
prawdopodobieństwem.

| Limit | Konfiguracja | Zachowanie |
|---|---|---|
| ryzyko na transakcję | `risk_per_trade_pct` (0.5 %) | wolumen = floor(budżet / strata na lot przy SL **z kosztami**) |
| ryzyko koszyka | `risk_per_basket_pct` (1 %) | `basket_loss_limit_x_risk × ryzyko` musi się zmieścić |
| dzienny limit straty | `daily_loss_limit_pct` (2 %) | BLOCK po przekroczeniu |
| ekspozycja | `max_exposure_lots[instrument]` | HEDGING liczony z max hedge (×(1+max_ratio)) |
| depozyt | `max_margin_use_pct` | z `order_calc_margin`. Przy braku wyceny decyduje order_check, a ostrzeżenie jest widoczne. |
| liczba pozycji | `max_open_positions` | hedge liczy się jako pozycja |
| spread / wiek notowania | `max_spread_usd`, `max_quote_age_s` | BLOCK |
| poślizg | `deviation_points` zlecenia, `max_slippage_usd` | broker odrzuca zlecenie poza dewiacją |
| cooldown / duplikat | `cooldown_minutes`, `duplicate_window_minutes` | BLOCK |
| min lot / krok | z terminala | podział 3 części, potem skonfigurowany fallback 2 części, inaczej BLOCK z powodem |
| tryb | AUTO_LIVE | **zablokowane dla SH** do czasu walidacji na danych klienta |
| tryb | AUTO_DEMO | wymaga trybu PEŁNEGO (skalibrowany model zdarzenia) i znanej prowizji |
| rachunek | HEDGING | wymaga rachunku hedging. Netting/exchange daje widoczny BLOCK, bez cichej podmiany. |

## Stan i restart

Każdy plan zapisuje w `sh_plans.fsm` serializowany automat stanu: Position albo Basket, razem ze zbiorami `seen_events` i
`issued`. Po restarcie zdarzenia już widziane nie zmieniają stanu, a wydane akcje nie są wydawane ponownie (test
`test_plan_once_per_signal_and_fsm_roundtrip`). Rekonsyliację z terminalem po restarcie opisuje etap 5/6
(`sh/service.py: recover`).

## Etap 4 – raport

* **Dodano:**
  * `sh/risk.py`, `sh/coordinator.py`, `sh/store.py`, `sh/executor.py`;
  * migracja 0023;
  * testy (14).
* **Sprawdzono:**
  * sizing z SL i kosztów;
  * fallback 2 części i BLOCK przy min locie;
  * HEDGING zablokowany na netting;
  * ekspozycja z hedge;
  * limity: dzienny, cooldown, duplikat, obcy właściciel, notowanie, spread, TTL;
  * AUTO_DEMO w trybie OGRANICZONYM zablokowane, AUTO_LIVE zablokowane;
  * pełna macierz koordynatora;
  * idempotencja akcji i jeden właściciel;
  * serializacja automatu stanu;
  * symulowany terminal (hedging): otwarcie z magic/komentarzem SH, retry bez duplikatu, partial wykonany raz, BE, odmowa
    obcej pozycji, odrzucenie, timeout UNKNOWN bez ponownej wysyłki;
  * PAPER: odrzucenie modyfikacji SL za ceną.
* **Zablokowane:**
  * test z prawdziwym terminalem demo wymaga MT5 klienta (Windows). W tym środowisku jest tylko symulator.
