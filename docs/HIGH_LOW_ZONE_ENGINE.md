# HIGH_LOW_ZONE_ENGINE – HLZE (`PMW-ZONES-HLZE-1`, `backend/masterquo/zones/hlze.py`)

Strefy szczytów i dołków M5/M15 z cyklem życia, równe szczyty/dołki, poziomy poprzedniego dnia, poprzedniej sesji, dnia bieżącego
i konsolidacji. Czyste funkcje serii zamkniętych świec ucinanej na `as_of` (bez informacji z przyszłości).
Architektura całości: [ZONE_ENGINE_ARCHITECTURE.md](ZONE_ENGINE_ARCHITECTURE.md).

## 1. Swingi

* Pivot = `strategies/indicators.pivots(high, low, left, right)`: szczyt ≥ `left` świec po lewej i **ściśle** wyższy od `right` świec
  po prawej (dołek symetrycznie). Domyślnie M5 left 3 / right 3, M15 left 3 / right 2 (`zones.swing_left`, `zones.swing_right`).
* **Istotność (prominence):** wychylenie pivotu względem okna `[p - left, p + right]` – dla szczytu `high[p] - min(low okna)`,
  dla dołka `max(high okna) - low[p]` – musi być ≥ `min_prominence_atr` × ATR14 (M5 0,6, M15 0,5). Mniejsze swingi są pomijane.
* **Czasy:** `created_at` = zamknięcie świecy pivotu; `confirmed_at` = zamknięcie świecy `p + right` (pierwszy moment, w którym bot
  mógł pivot znać). Nic nie jest datowane wstecz na świecę pivotu.
* **Prowizoryczne:** kandydaci w ostatnich `right` świecach (prawa strona niekompletna) – status `PROVISIONAL`, `confirmed_at` = null,
  kara −10 w punktacji, na wykresie linia przerywana i dopisek „PROW.”. Nie są używane jako potwierdzony poziom.

## 2. Granice strefy

* Szczyt: `[max(góra korpusu, high − k·ATR), high]`; dołek: `[low, min(dół korpusu, low + k·ATR)]`, `k` = `zone_half_width_atr` (0,25).
* Minimalna szerokość `min_width_ticks` (5 ticków); zaokrąglenie do ticka instrumentu.
* Szersza niż `max_zone_width_atr` × ATR (1,5) → flaga `WIDE` (kara −10); szersza niż 2 × to → **odrzucona** (za szeroka, by nieść
  informację o wejściu lub unieważnieniu).

## 3. Cykl życia (tylko świece po `confirmed_at`)

```
PROVISIONAL ─(potwierdzenie)─> ACTIVE ─(test po wyjściu ze strefy ≥ retest_gap_bars)─> TESTED ─(testy ≥ weaken_after_retests)─> WEAKENED
                                  │                                                       
                                  ├─(knot poza zewnętrzną granicą + zamknięcie po stronie strefy w ≤ reclaim_bars)─> SWEPT
                                  ├─(ZAMKNIĘCIE poza granicą o ≥ break_close_atr × ATR)─> BROKEN ─> BREAKOUT_LEVEL / BREAKDOWN_LEVEL
                                  └─(wiek > max_age_bars)─> EXPIRED
```

* **Test:** świeca dotyka strefy (tolerancja `touch_tol_atr` 0,1 ATR). Kolejny test liczy się dopiero po wyjściu ze strefy na
  ≥ `retest_gap_bars` (3) świec – kilka świec w strefie to jeden test.
* **Więcej testów ≠ silniejsza strefa:** po `weaken_after_retests` (3) testach status WEAKENED, a w punktacji świeżość traci 2 pkt
  za każdy test ponad próg (testy mogą zużywać leżącą tam płynność).
* **Sweep:** knot poza strefą (więcej niż tolerancja) i zamknięcie z powrotem po stronie strefy w tej samej świecy albo w ciągu
  `reclaim_bars` (3) świec. **Sam knot nie jest ani sweepem, ani przełamaniem** – wymagana jest odpowiedź ceny (zamknięcie z powrotem).
* **Przełamanie wyłącznie zamknięciem** poza zewnętrzną granicą o ≥ `break_close_atr` (0,1) ATR. Przełamany szczyt kontynuuje jako
  `BREAKOUT_LEVEL` (potencjalne wsparcie), przełamany dołek jako `BREAKDOWN_LEVEL` – od zamknięcia świecy przełamania, z własnym cyklem życia.
* **Wygaśnięcie:** wiek > `max_age_bars` (M5 576 = 2 dni, M15 384 = 4 dni).
* Każda zmiana ma zdarzenie z czasem (`RETEST`, `SWEEP_RECLAIMED` z czasem knota, `BROKEN_BY_CLOSE`); 12 ostatnich w strefie,
  pełny dziennik w `data/zones/zones.sqlite`.

## 4. Kategorie

| Typ | Źródło | Znany od |
|---|---|---|
| SWING_HIGH / SWING_LOW | pivot M5 / M15 | `confirmed_at` pivotu |
| EQUAL_HIGHS / EQUAL_LOWS | ≥ 2 potwierdzone pivoty tego samego rodzaju w tolerancji `cluster_tol_atr` (0,25 ATR), odstęp ≥ `min_cluster_gap_bars` (3) | potwierdzenie drugiego pivotu |
| PREVIOUS_DAY_HIGH / LOW | ostatni zamknięty słupek D1 brokera (dzień serwera MT5) | zamknięcie tego D1 |
| INTRADAY_HIGH / LOW | ekstrema bieżącego dnia brokera | zawsze PROVISIONAL (zmieniają się do końca dnia) |
| PREVIOUS_SESSION_HIGH / LOW | ostatni boks FINAL każdej sesji z `analytics/session_engine`; stan krawędzi (SWEPT/BROKEN/EXPIRED) = status | `known_at` boksu |
| CONSOLIDATION_HIGH / LOW | `analysis/range_m5.detect` | `available_at` zakresu |
| BREAKOUT_LEVEL / BREAKDOWN_LEVEL | przełamany swing (zmiana roli) lub zakres przełamany zamknięciem | zamknięcie świecy przełamania |
| LIQUIDITY_CLUSTER | w UZICE: równe szczyty/dołki pokrywające się z ekstremum dnia/sesji | jak członkowie |

**Płynność jest wyłącznie wnioskowana:** równe szczyty/dołki i oczywiste ekstrema dostają `liquidity.inference = "INFERRED"`
(prawdopodobne zlecenia stop powyżej szczytów / poniżej dołków). Silnik nigdy nie podaje ilości zleceń – nie ma takich danych.

## 5. M5 i M15

Oba TF liczone niezależnie (osobne parametry swingów, wieku i istotności). Pokrywające się strefy M5 i M15 tej samej polaryzacji
łączy UZICE (składnik `mtf` +10); M15 swing waży w strukturze 10 pkt, M5 6 pkt. Na wykresie M5 widać strefy z TF M5 i D1,
na M15 – z M15 i D1, na innych TF – całą mapę.

## 6. Parametry (`config.zones`, wartości projektowe – nie optymalizowane na danych)

| Parametr | Domyślnie | Parametr | Domyślnie |
|---|---|---|---|
| `tfs` | M5, M15 | `touch_tol_atr` | 0,10 |
| `swing_left` | M5 3, M15 3 | `break_close_atr` | 0,10 |
| `swing_right` | M5 3, M15 2 | `reclaim_bars` | 3 |
| `min_prominence_atr` | M5 0,6, M15 0,5 | `retest_gap_bars` | 3 |
| `zone_half_width_atr` | 0,25 | `weaken_after_retests` | 3 |
| `min_width_ticks` | 5 | `max_age_bars` | M5 576, M15 384 |
| `max_zone_width_atr` | 1,5 | `cluster_tol_atr` / `min_cluster_gap_bars` | 0,25 / 3 |

## 7. Ograniczenia

* Kolejność wewnątrz świecy jest nieznana: świeca, która przebija obie strony strefy, jest oceniana tylko po zamknięciu.
* Dzień = dzień serwera brokera (słupek D1 MT5), nie dzień kalendarzowy UTC.
* Heurystyki szerokości i istotności są oparte na ATR; nie twierdzą, że strefa „zadziała” – to opis struktury, nie prognoza.
