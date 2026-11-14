# Ryzyko i jednostki pakietu 20 strategii

## Jednostki

* `instrument_id = XAUUSD`, `broker_symbol` z mapowania aplikacji (np. `XAUUSD-`) – bez zgadywania podobnego symbolu.
* `pip_size = 0,10`, `pip_definition = PMW_XAU_PRICE_0_10_V1` (jawna konwencja produktu); `distance_price = pips × pip_size`.
  25 pips = 2,50 USD zmiany ceny; 40 pips = 4,00 USD – niezależnie od liczby cyfr. Brak definicji = `PIP_DEFINITION_UNRESOLVED`.
* `point`, `trade_tick_size`, `digits`, lot, wartość ticka – z MT5. Kwantyzacja do ticka **na zewnątrz** (SL dalej, TP dalej), po
  zaokrągleniu RR liczone ponownie.
* BUY wchodzi po Ask i zamyka po Bid; SELL wchodzi po Bid, zamyka po Ask. Świece MT5 są Bid – porównanie „ucieczki” ceny Bid vs Bid.

## RR planu (SC) i koszyka (HG)

```
r = |E − S|, d1 = |TP1 − E|, d2 = |TP2 − E|, w1 = w2 = 0,5
rr_plan_net          = (w1 d1 + w2 d2 − C_win) / (r + C_loss)
d2_required          = (rr_min (r + C_loss) + C_win − w1 d1) / w2
rr_basket_net_target = (w1 d1 + w2 d2 − C − HL) / (r + C + HL)        HL = ratio × (luka hedge→powrót + C)
```

* `C` = 2 × poślizg + prowizja round trip (normalizowana na jednostkę wolumenu: prowizja partiali proporcjonalna do wykonanego wolumenu,
  więc jedna prowizja round trip, nie dwie). Spread jest w cenach Ask/Bid i **nie** jest odejmowany drugi raz.
* Nieznana prowizja → scenariusz (`commission_scenario_price_rt`, domyślnie 0,10 USD ceny), `cost_status = ESTIMATED_SCENARIO`; plan
  nigdy nie jest `NET_VALIDATED` ani `READY_TO_EXECUTE`, a tryby AUTO wymagają znanej prowizji (reguła istniejącego silnika ryzyka).
* `HL` – ograniczona strata nogi hedge w ścieżkach celu (model scenariuszowy, `policies.hedge_loss_bound`): poziomowe polityki
  (L, środek kanału, OR, poziom wybicia, VAL, EMA20/AVWAP ± b) – luka 2 × b_M5 + 0,25 r; HG04 – (OR_high + b) − środek OR + 0,25 r;
  HG09/HG10 (warunki dynamiczne) – parametr scenariusza 0,5 r. Bez ograniczenia → `RR_NOT_ESTIMABLE`, nie 3,0.
* Przykłady specyfikacji (testy `tests/test_sh_pack.py`): SC 3000 / 2998,75 / 3002,50 / 3003,75, C = 0,15 → 2,125; HG 3000 / 2998 /
  3004 / 3010, C = 0,25 → 3,0; ten sam HG z kosztem hedge 0,30 w ścieżce celu → 2,867 (< 3,0); TP1 1R + TP2 2R → RR ważone 1,5 (nie 2).
* SL wynika z unieważnienia i bufora `b`; nigdy nie jest skracany, aby osiągnąć RR. Jeśli wymagany TP2 nie mieści się przed najbliższym
  przeciwnym poziomem znanym przy wejściu (swing TF sygnału / kontekstu, maksimum poprzedniej doby) albo przekracza heurystykę zasięgu
  ATR × √(czas pozycji / TF) – `NO_TRADE / TARGET_UNREACHABLE` (heurystyka, nie prawdopodobieństwo).

## Scenariusze koszyka (raportowane w planie)

`NO_HEDGE_BOTH_TP`, `STOP_NO_HEDGE`, `TP1_THEN_STOP`, `GAP_STRESS_STOP` (+1,00 USD luki, +0,20 poślizgu), a dla HG także
`HEDGE_RETURN_BOTH_TP`, `HEDGE_WHIPSAW_STOP` (najgorsza ograniczona), `HEDGE_CONTINUE_STOP`, `PARTIAL_BEFORE_ACTIVATION`, `HEDGE_REJECTED`,
`TIMEOUT` – w R początkowego budżetu ryzyka koszyka. To właściwość zdefiniowanych scenariuszy, nie gwarancja maksymalnej straty.

## Sizing i wykonanie

* Wolumen z istniejącego silnika ryzyka (`sh/risk.py`): budżet ryzyka / strata na lot przy SL **z kosztami i ograniczoną stratą hedge**
  (`costs.round_trip_price = C + HL`), limity ekspozycji (dla HG w najgorszym przypadku baza + max ratio), depozyt, dzienna strata,
  liczba pozycji, cooldown, duplikaty, obcy właściciel. Oba partiale muszą osiągać min. lot – inaczej `PARTIAL_VOLUME_INFEASIBLE`
  (bez zwiększania lota). Noga hedge musi osiągać min. lot przy `ratio × wolumen` – inaczej `HEDGE_VOLUME_INFEASIBLE`.
* Plan zachowuje **planowane** absolutne TP1/TP2/SL. Po fillu raportowane jest odchylenie i RR przy fillu; RR < 90 % minimum, fill za SL
  albo za TP1 → zdefiniowane wcześniej wyjście (`ENTRY_ABORT`). Brak cichego przesuwania poziomów.
* Hedge: tylko po fillu bazy, tylko rachunek HEDGING (NETTING → odmowa z powodem, aktywacja zużyta), jedna aktywacja w życiu koszyka,
  ratio ≤ 0,50 aktualnej bazy (zaokrąglenie w dół), po TP1 nadwyżka hedge jest zamykana. Intencja `HEDGE` w IntentLedger z rezerwacją
  RiskBook. Noga hedge ma ochronę brokerską (SL = TP2 bazy, TP = SL bazy). Timeout hedge bez warunku powrotu → wyjście całego koszyka.
  TP2 / SL bazy / wyjście koszykowe → zamknięcie hedge. STOP blokuje nowy hedge, nie wyjścia.
* `initial_risk_money` zapisywany raz (rezerwacja / plan), historyczny mianownik R nie jest zmieniany po partialu.
