# Specyfikacje 20 wariantów (PMW-SH-PACK-2.0.0) – reguły i parametry zaimplementowane

Kod: `backend/masterquo/sh/pack/detectors.py` (wejścia), `policies.py` (hedge), `solver.py` (TP/SL/RR), parametry
`config/sh_strategy_pack_v2.json` (+ nadpisania z panelu `data/sh/pack_override.json`). Każdy wariant ma `config_hash`; zmiana dowolnego
parametru zmienia hash i dotyczy nowych kandydatów (otwarte plany mają zamrożony wariant).

## Wspólne reguły (§3.4)

* `t` = ostatnia zamknięta świeca TF sygnału; trigger na jej zamknięciu; fill najwcześniej na następnym ticku (BUY Ask, SELL Bid).
* `b = max(2 × tick, 0,10 × ATR14(TF))` (ATR Wildera, zamknięte świece); w warunkach hedge osobne `b` z M5.
* Swing potwierdzony: pivot 2/2, znany dopiero po zamknięciu dwóch prawych świec.
* TrendUp(H1): close > EMA50 > EMA200, EMA50[t] > EMA50[t−3]. TrendUp(M5/M15/M1/M3 jako kontekst): close > EMA20 > EMA50, EMA20 rośnie
  (3 świece). „Silny przeciwny trend” = przeciwny TrendUp + ADX14 ≥ 25. Rozgrzewka: 5 × najdłuższa EMA danego TF (H1: 1000 świec) – brak
  historii = `WARMING_UP`, nigdy „neutralny”.
* Range(M15): ADX14 < 20 i |EMA20[t] − EMA20[t−5]| < 0,25 ATR14.
* Retest: w ≤ 3 kolejnych świecach zakres dotyka [L−b, L+b], zamknięcie po stronie wybicia, close > open; poziom zamrożony przed wybiciem.
* SELL = lustro BUY: reguła liczona na widoku z zanegowanymi cenami (o'=−o, h'=−l, l'=−h, c'=−c) – wszystkie nierówności i strony
  odwracają się jednocześnie.
* TTL wejścia: 3 świece TF triggera, maks. 10 min (SC) / 30 min (HG); najwcześniejszy limit. Ucieczka ceny > 0,25 ATR od zamknięcia
  triggera (Bid vs Bid) = WAIT (bez pogoni). Zamknięcie za poziomem unieważnienia przed fillem = INVALIDATED.
* Sesje (IANA, DST): OR Londyn 08:00–08:15 `Europe/London`, Nowy Jork 08:20–08:35 `America/New_York`; doba handlowa 17:00–17:00
  `America/New_York` (kotwica VWAP sesji, profil poprzedniej doby).

## Cele

| Rodzina | TP1 | TP2 | Minimum | Udziały |
|---|---|---|---|---|
| SC | ≥ max(25 pips = 2,50 USD, 1,5 r) | ≥ max(TP1 + tick, 3 r, wymagane przez RR) | RR planu netto ≥ 2,0 | 50 % / 50 % |
| HG | ≥ max(40 pips = 4,00 USD, 2 r) | ≥ max(TP1 + tick, 5 r, wymagane przez RR koszyka) | RR koszyka netto (scenariusz celu) ≥ 3,0 | 50 % / 50 % |

Dokładnie dwa TP, bez BE (po TP2 nie zostaje runner). Cele naturalne (SC07: środek / górne pasmo BB; SC10, HG08: POC / VAH) są przyjmowane
tylko, gdy same spełniają minima – nigdy nie są przesuwane.

## Warianty HEDGING (sygnał → hedge → powrót; ratio; limit hedge / baza)

| ID | TF | Wejście BUY (SELL lustrzanie) | SL | Hedge | Unwind | Ratio | Limity |
|---|---|---|---|---|---|---|---|
| HG01 | M5, M15 | kontekst TrendUp(M15) i TrendUp(H1); w 5 świecach dotknięcie EMA20±b bez zamknięcia pod chronionym swingiem; close > EMA20+b i > high[t−1] | min(minimum korekty, chroniony swing) − b | MAE ≥ 0,5 r i dwa zamknięcia M5 < EMA20−b, H1 ważny | close M5 > EMA20+b i > high[t−1] | 0,50 | 30 / 240 min |
| HG02 | M5, M15 | TrendUp(H1); wybicie potwierdzonego oporu L (zamrożonego przed wybiciem), retest w 3 świecach | min(minimum retestu, chroniony swing) − b | close < L−b, potem close < L (gdy L−b ≤ SL+2C: EXIT) | close > L+b i kolejna utrzymuje L | 0,50 | 20 / 180 |
| HG03 | M15 | TrendUp(H1), ADX14 ≥ 25; close > max 20 poprzednich świec, retest | ostatni potwierdzony swing low / minimum retestu − b | dwa close M5 < środek kanału − b (gdy środek−b ≤ SL: brak hedge) | dwa close M5 > środek + b | 0,25 | 45 / 360 |
| HG04 | M5 | H1 zgodny lub neutralny; OR zamrożony, close > OR_high+b, retest; wejścia ≤ 90 min po OR, jedno na kierunek i sesję | min(minimum retestu, OR_low) − b | close < OR_high−b, potem close < środek OR | close > OR_high+b | 0,50 | 20 / 180 |
| HG05 | M5, M15 | TrendUp(H1); wcześniej nad AVWAP, korekta do AVWAP±b, close > AVWAP+b i > high[t−1] (brak tick volume = NO_DATA) | minimum retestu − b | dwa close M5 < AVWAP−b | dwa close M5 > AVWAP+b | 0,50 | 30 / 240 |
| HG06 | M5 | M15/H1 bez przeciwnego trendu; BandWidth < 20. percentyl ze 120 w 5 świecach, close > górne pasmo(t−1) i > max(10)+b, ATR rośnie; retest | minimum retestu − b | dwa close M5 pod poziomem wybicia, korpus ostatniej > 0,8 ATR, minimum kompresji ważne | close > poziom+b i > high[t−1] | 0,50 | 15 / 180 |
| HG07 | M5, M15 | H1 bez silnego przeciwnego trendu; low < L−b, close > L+b (ta sama lub następna), kolejna przebija high świecy reclaim | ekstremum sweepu − b | close < L−b i kolejny < L, nad ekstremum (strefa L–SL < 2C: EXIT) | close > L+b | 0,25 | 15 / 120 |
| HG08 | M5 | Range(M15), H1 bez silnego przeciwnego trendu; profil poprzedniej doby: low < VAL−b, close > VAL+b, następna nad high | ekstremum odrzucenia − b | dwa close M5 < VAL−b | close > VAL+b | 0,25 | 15 / 120 |
| HG09 | M5, M15 | TrendUp(H1), EMA20 > EMA50, korekta 2–5 świec bez złamania swingu, close > max(high t−1, t−2)+b; σ (std log-zwrotów 60 M5) poniżej 95. percentyla | minimum korekty − b | σ_teraz/σ_wejście ≥ 1,5 i przeciwna M5 > 0,5 ATR; ratio = clip(1 − σ_wejście/σ_teraz; 0,25; 0,50) jednorazowo | 3 kolejne M5 z σ-ratio ≤ 1,2 i close > EMA20 | 0,25–0,50 | 30 / 240 |
| HG10 | M5, M15 | detektor HG01 (ta sama grupa – nie drugi głos) | j.w. | MFE ≥ 1,5 r, oddanie ≥ 0,5 r i close M5 < EMA9 | close > EMA9+b i > lokalne maksimum sprzed korekty | 0,50 | 20 / 240 |

Wariant GARCH dla HG09 jest wymieniony jako osobny (wymaga READY/zwalidowanego modelu) – **nie jest zaimplementowany jako podmiana**.

## Warianty SCALPING

| ID | TF | Kontekst | Wejście BUY (SELL lustrzanie) | SL | Maks. pozycja |
|---|---|---|---|---|---|
| SC01 | M1, M3 | TrendUp M5 i M15 | dotknięcie EMA20±b w 5 świecach bez zamknięcia pod chronionym swingiem; close > EMA20+b i > high[t−1] | minimum korekty − b | 30 min |
| SC02 | M1, M3 | M15 zgodny lub neutralny | ≥ 2 close pod VWAP doby w 5 świecach, przebicie VWAP+b, retest VWAP±b ze wzrostowym zamknięciem w ≤ 3 świecach; > 4 przecięcia w 10 świecach odrzuca | minimum sekwencji − b | 30 |
| SC03 | M1, M3, M5 | M15 bez silnego przeciwnego trendu | OR zamrożony, close > OR_high+b, retest; ≤ 60 min po OR; jedno na kierunek i sesję | minimum retestu − b | 30 |
| SC04 | M3, M5 | TrendUp M15, ADX14 TF ≥ 25 | close > max 20 poprzednich + b, ATR nie spada, retest | minimum retestu − b | 45 |
| SC05 | M1, M3, M5 | M5/M15 zgodne lub neutralne | BandWidth < 20. percentyl w ≥ 3 z 5 świec, close > górne pasmo(t−1) i > max(10)+b, ATR rośnie | minimum 3 świec − b | 30 |
| SC06 | M1, M3 | Range(M15) albo trend M15 zgodny | low < L−b (L: swing low M5 lub minimum poprzedniej doby), close > L+b, następna zamyka się nad high reclaim | ekstremum sweepu − b | 20 |
| SC07 | M1, M3 | Range(M15), ADX M5 < 20 | low t−1 < dolne pasmo, t wraca do pasm nad high[t−1], RSI14 z ≤ 30 na > 30 | minimum dwóch świec − b; cele: środek i górne pasmo | 20 |
| SC08 | M1, M3 | TrendUp M5 i M15 | %K < 20 w korekcie (6 świec), %K przecina %D w górę, close > high[t−1] i > EMA50 | minimum korekty − b | 30 |
| SC09 | M3, M5 | TrendUp M15 | linia MACD > 0 (3 świece), histogram ≤ 0 w korekcie i przejście > 0 na t, close > high[t−1] i > EMA20 | potwierdzone minimum korekty − b | 45 |
| SC10 | M1, M5 | Range(M15) | profil poprzedniej doby: low < VAL−b, close > VAL+b, następna nad high; cele POC i VAH | ekstremum odrzucenia − b | 30 |

Grupy logiki (nie są niezależnymi głosami): `TREND_PULLBACK_EMA` (SC01, SC08, SC09, HG01, HG09, HG10), `BREAKOUT_RETEST`, `CHANNEL_BREAKOUT`
(HG03, SC04), `OPENING_RANGE` (HG04, SC03), `VWAP` (HG05, SC02), `SQUEEZE_BREAKOUT` (HG06, SC05), `SWEEP_RECLAIM` (HG07, SC06),
`VALUE_AREA` (HG08, SC10), `RANGE_REVERSION` (SC07).
