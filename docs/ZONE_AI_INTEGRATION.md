# ZONE_AI_INTEGRATION – strefy w ocenie setupów i w cechach ML

Jak mapa stref ([ZONE_ENGINE_ARCHITECTURE.md](ZONE_ENGINE_ARCHITECTURE.md)) trafia do warstwy oceny setupów (SHADOW) i do
pipeline'u cech ML – bez automatycznego retreningu i bez podmiany modeli produkcyjnych.

## 1. Zasada

Strefy są **dowodem kontekstowym**, nie bezwarunkową regułą. Ostateczna decyzja należy do logiki strategii, R:R, prawdopodobieństwa
(jeśli jest skalibrowane) i warstwy wykonania. Wynik strefy 0–100 nie jest prawdopodobieństwem i nie jest nim nigdzie zastępowany.

## 2. Kontekst strefowy setupu (`zones/features.py`, `PMW-ZONE-FEAT-1`)

`ZoneService.context_for(direction, entry, stop, cost_price)` / `GET /api/v1/zones/context` zwraca:

| Pole | Znaczenie |
|---|---|
| `map_id`, `map_as_of`, `data_state` | z której mapy pochodzi kontekst i czy dane są OK |
| `opposing_zone` | najbliższa żywa strefa przeciwna (dla LONG – opór powyżej wejścia, dla SHORT – wsparcie poniżej): typ, granice, wynik, status, flagi |
| `supporting_zone` | najbliższa strefa po stronie stopu (wsparcie dla LONG / opór dla SHORT) |
| `room_after_costs_r` | (odległość do strefy przeciwnej − koszt) / R, R = \|wejście − stop\| |
| `flags` | `ZONE_ROOM_INSUFFICIENT` – strefa przeciwna z wynikiem ≥ `strong_zone_score` (60) bliżej niż `min_room_r` (1,0 R) po kosztach; `ZONE_CONFLICT_AHEAD` – strefa przeciwna jest w konflikcie polaryzacji |
| `session_context` | kontekst sesji DSVIE (położenie względem VA, wolumen względny, migracja POC …) |
| `features` | 26 cech poniżej |

Pełna mapa daje też: najbliższe wsparcie/opór (`summary`), płynność wnioskowaną (`liquidity`), POC/VA (`profiles`), status i reguły
unieważnienia strefy (`invalidation_rules`), konflikty (`conflicting_zone_ids`), jakość danych (`data.state`).

## 3. Ocena setupów SHADOW (`evaluation/`)

* `EvaluationService._log` pobiera kontekst dla każdego kandydata (S01–S12, SCALPING/HEDGING, scalp SHADOW).
* **Strażnik look-ahead:** kontekst z mapy o `as_of` późniejszym niż czas decyzji jest odrzucany (test `EvaluationLookAhead`).
* Kontekst trafia do `SetupAssessment.zone_context` i do `features["zones"]` kandydata w ledgerze (NaN zapisywane jako null);
  `GET /api/v1/eval/assessments` pokazuje `zone_context`.
* Reguła decyzji oceny: jeżeli `data_state == OK` i flaga `ZONE_ROOM_INSUFFICIENT`, a ocena byłaby ACCEPT → **REDUCE**
  (`ZONE_ROOM_INSUFFICIENT`). Mapa w innym stanie → tylko notatka, bez wpływu. Strefy nie tworzą prawdopodobieństwa – bez
  skalibrowanego modelu ocena pozostaje DEFER.
* Ocena jest SHADOW: nie otwiera, nie blokuje i nie zmniejsza zleceń. Wpływ na wykonanie wymagałby walidacji (§6) i osobnej zgody.

## 4. Cechy ML (`ml/features.py`, schemat `MQ-FEAT-1.1.0`)

* 1.1.0 = 1.0.0 + blok 26 cech `zone_*`. `zone_block()` wywołuje **ten sam** `zones.engine.compute_map` na cięciu as-of widoku
  (ostatnie 600 świec M5/M15/H1/D1, tylko zamknięte), z parametrami `ZonesConfig()` zamrożonymi dla wersji schematu (zmiana
  ustawień w panelu nie zmienia cech treningowych po cichu).
* Błąd obliczenia stref = cechy NaN (brak danych), nigdy wartość podstawiona.
* **Zgodność:** `COMPATIBLE_SCHEMAS = (MQ-FEAT-1.0.0, MQ-FEAT-1.1.0)`. Trener przyjmuje mieszane próbki (stare bez cech stref → NaN;
  preprocessor wybiera kolumny tylko z bloku treningowego). Model zapisany na 1.0.0 ładuje się dalej i czyta własną listę kolumn –
  działający czempion jest bez zmian.
* **Brak automatyzmów:** nie ma automatycznego retreningu, a nowy model z cechami stref jest zwykłym kandydatem: promocja według
  istniejących reguł (O8: zysk Briera > 2 błędy standardowe ponad wskaźnik bazowy, walidacja walk-forward z kosztami) i ręcznej decyzji.

### Lista cech (`zones/features.py: NAMES`)

| Cecha | Definicja |
|---|---|
| `zone_dist_m5_high_atr`, `zone_dist_m5_low_atr`, `zone_dist_m15_high_atr`, `zone_dist_m15_low_atr` | odległość (ATR M5) do najbliższej potwierdzonej strefy szczytu powyżej / dołka poniżej, osobno M5 i M15 |
| `zone_dist_poc_atr`, `zone_dist_vah_atr`, `zone_dist_val_atr` | odległość do POC/VAH/VAL ostatniego zakończonego profilu, ze znakiem kierunku transakcji |
| `zone_va_position` | +1 powyżej VA, 0 w VA, −1 poniżej (× kierunek) |
| `zone_hvn_near`, `zone_lvn_near` | HVN / LVN ostatniego profilu w promieniu 0,5 ATR |
| `zone_dist_demand_atr`, `zone_dist_supply_atr` | odległość do najbliższej strefy popytu poniżej / podaży powyżej |
| `zone_opp_dist_r`, `zone_opp_room_after_costs_r` | odległość do strefy przeciwnej w R, przed i po kosztach (w ocenie: koszt z modelu kosztów oceny; w cechach ML: spread widoku w chwili decyzji, brak spreadu → NaN) |
| `zone_opp_score`, `zone_opp_width_atr`, `zone_opp_age_bars`, `zone_opp_retests` | cechy strefy przeciwnej |
| `zone_own_dist_r`, `zone_own_score`, `zone_own_swept` | strefa po stronie stopu: odległość w R, wynik, czy była sweepnięta |
| `zone_session` | 0 Azja, 1 Londyn/Europa, 2 Nowy Jork/US, −1 poza sesją |
| `zone_relvol`, `zone_poc_migration` | wolumen względny sesji; migracja POC × kierunek |
| `zone_data_ok`, `zone_volume_source` | 1 gdy mapa OK; 0 brak / 1 tick volume / 2 wolumen giełdowy |

## 5. Wersjonowanie

Mapa niesie `versions` (map/hlze/dsvie/uzice/schema), ocena zapisuje `map_id`, próbka ML – wersję schematu cech. Zmiana reguł
silnika stref = nowa wersja modułu; zmiana definicji cech = nowa wersja schematu MQ-FEAT (z listą zgodności).

## 6. Walidacja predykcyjna – plan (jeszcze niewykonana)

Nie twierdzimy, że strefy poprawiają wynik. Warunek jakiegokolwiek wpływu poza SHADOW:

1. Zebrać ≥ 200 dojrzałych ocen SHADOW z `zone_context` (licznik gotowości O2 w raporcie oceny).
2. Porównanie walk-forward (z embargo, koszty spread + poślizg + prowizja): ten sam model z cechami stref i bez nich – Brier,
   log loss, kalibracja, wynik netto w R z przedziałem ufności; osobno grupy ZONE_ROOM_INSUFFICIENT vs reszta.
3. Wynik dodatni tylko, jeśli różnica przekracza 2 błędy standardowe (jak reguła O8); inaczej strefy zostają opisowe.
4. Ewentualna zmiana wykonania (np. zmniejszenie wielkości przy braku miejsca) – osobny wniosek i jawna zgoda; LIVE bez zmian.
