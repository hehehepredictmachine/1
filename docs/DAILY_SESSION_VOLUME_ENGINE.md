# DAILY_SESSION_VOLUME_ENGINE – DSVIE (`PMW-ZONES-DSVIE-1`, `backend/masterquo/zones/dsvie.py`)

Profile wolumenu sesji, kontekst sesji i strefy popytu/podaży oparte na dowodach. Architektura całości:
[ZONE_ENGINE_ARCHITECTURE.md](ZONE_ENGINE_ARCHITECTURE.md).

## 1. Źródło wolumenu – zawsze podane, nigdy przełączane po cichu

| `volume_source.source` | Kiedy | Co znaczy |
|---|---|---|
| `TICK_VOLUME` | ≥ 50% świec ma `tick_volume` > 0 | liczba zmian ceny w świecy u brokera = **wskaźnik aktywności**. Dla OTC XAUUSD to aktywność kwotowań tego brokera, nie globalny wolumen złota i nie wolumen kupujących/sprzedających |
| `EXCHANGE_VOLUME` | ≥ 50% świec ma `real_volume` > 0 | wolumen transakcyjny tego źródła (instrumenty giełdowe) |
| `NONE` | brak użytecznego wolumenu | profile `INVALID`, składnik wolumenu w punktacji = 0 |

`order_flow`, `footprint`, `order_book` = **UNAVAILABLE**: świece nie mają podziału bid/ask, a ticki `COPY_TICKS_INFO` to wyłącznie
kwotowania. Żadna strefa nie jest opisana jako zweryfikowany wolumen inicjowany przez kupujących lub sprzedających
(`order_flow_verified = false` w każdej strefie popytu/podaży). Wolumen tickowy brokera nie jest nigdzie przedstawiany jako
globalny ani jako wolumen agresorów.

## 2. Sesje

Okna z `analytics/session_engine` (jedna definicja sesji w bocie), profil wg instrumentu (`zones.session_profile`):

* `LAB_XAU_REFERENCE_V1`: ASIA 09:00–15:00 Asia/Tokyo, LONDON 08:00–16:30 Europe/London, NEW_YORK 08:20–13:30 America/New_York;
* `LAB_BTC_REFERENCE_V1`: ASIA 08:00–16:00 Asia/Singapore, EUROPE 08:00–16:30 Europe/London, US 09:30–16:00 America/New_York.

Godziny lokalne + strefa IANA, więc zmiana czasu (DST) przesuwa okno w UTC automatycznie, osobno dla Londynu i Nowego Jorku
(np. LONDON 23.10.2026 = 07:00 UTC, 26.10.2026 = 08:00 UTC; NEW_YORK do 1.11.2026 nadal 12:20 UTC – test `test_dst_session_boundaries`).
Własne sesje = nowy profil w `session_engine.PROFILES` (wersjonowany) i wpis w `zones.session_profile`.

## 3. Profil sesji

* Wejście: zamknięte świece `profile_tf` (M5), w całości wewnątrz okna i zamknięte nie później niż `min(koniec okna, as_of)` –
  żadna przyszła świeca. Do 2016 M5 historii (7 dni) czytanych przez `ZoneService`.
* **Metoda `UNIFORM_RANGE_ALLOCATION_FROM_CANDLES`:** wolumen świecy rozłożony na przedziały cenowe (bin `zones.bin_size`:
  XAUUSD 0,5, BTC 25) proporcjonalnie do pokrycia zakresu low–high; świeca bez zakresu → jeden bin. To **szacunek ze świec**, nie
  profil z transakcji (nie wiadomo, gdzie w świecy był handel).
* **POC** = bin o największym wolumenie (remis → niższa cena), cena = środek binu.
* **Value area** (`value_area_pct` 70%): rozszerzanie od POC o jeden bin w stronę większego wolumenu (remis → w dół) aż do ≥ 70%
  sumy; VAH/VAL = zewnętrzne krawędzie zakresu.
* **HVN** = lokalne maksima histogramu wygładzonego średnią z `node_smoothing_bins` (3) binów, ≥ `hvn_min_share_of_poc` (0,6) × maksimum,
  bez POC. **LVN** = lokalne minima ≤ `lvn_max_share_of_peaks` (0,35) × mniejszego z najwyższych binów po obu stronach.
* **Stany:** `DEVELOPING` (okno trwa), `COMPLETED` (okno zakończone i pokrycie ≥ `min_profile_coverage` 90% oczekiwanych świec –
  odtwarzalny: późniejsze dane go nie zmieniają), `INVALID` (pokrycie za małe – podana przyczyna – albo brak wolumenu),
  `STALE` (rozwijający się, a najnowsza świeca starsza niż 3 świece; mapa dostaje stan DEGRADED). Brak świec w oknie (rynek zamknięty)
  = brak profilu – nic nie jest dopisywane.
* **Ścieżka POC** rozwijającego się profilu (24 ostatnie punkty, każdy z czasem, w którym był znany) i **migracja POC**
  (`poc_migration_bins` = POC teraz − POC w połowie ścieżki, w binach).
* **Wolumen względny:** suma wolumenu sesji od początku do tego samego czasu trwania, podzielona przez średnią z ≤ 5 poprzednich
  **zakończonych** sesji tej samej nazwy w tym samym czasie od początku (`relative_volume`, liczba sesji bazowych obok). Nie ma jednego
  uniwersalnego progu „wysokiego wolumenu”.

## 4. Kontekst sesji (`map.context`)

`current_session`, położenie ceny względem value area rozwijającego się i poprzedniego zakończonego profilu (ABOVE_VA / INSIDE_VA /
BELOW_VA), `acceptance_outside_previous_va` (6 ostatnich zamknięć powyżej VAH / poniżej VAL), `returned_to_previous_poc` (czy
w bieżącej sesji cena dotknęła poprzedniego POC), `developing_poc_stable` (POC w ostatnich 6 punktach ścieżki w zakresie 2 binów),
`relative_volume`, `poc_migration_bins`.

## 5. Strefy popytu / podaży – tylko z dowodami

Kandydat = potwierdzony swing dołka (popyt) / szczytu (podaż), który spełnia **wszystkie**:

1. **odrzucenie** na świecy pivotu (knot po stronie pivotu ≥ 40% zakresu świecy albo zamknięcie oddalone od ekstremum o ≥ 60% zakresu),
2. **przemieszczenie** ≥ `displacement_atr` (1,0) ATR w ciągu `displacement_bars` (6) świec,
3. **co najmniej jeden element kontekstu:**
   * poziom profilu (POC, VAL dla popytu / VAH dla podaży, LVN, HVN) profilu **zakończonego przed potwierdzeniem pivotu**, w tolerancji;
   * ekstremum poprzedniego dnia lub sesji tej samej strony;
   * aktywność tickowa świecy pivotu ≥ 1,5 × mediana 20 poprzednich świec (obserwacja aktywności, nie wolumen agresorów).

Sama akcja ceny nie tworzy strefy popytu/podaży (test `test_price_action_alone_is_not_demand`). Każdy dowód ma typ:
`PRICE_ACTION_INFERENCE` (swing, odrzucenie, przemieszczenie, zbieżność z ekstremum) albo `VOLUME_OBSERVATION` (poziom profilu,
skok aktywności tickowej, ze źródłem wolumenu w opisie). Typu „zweryfikowany order flow” nie ma, bo nie ma takich danych.
Strefa jest znana od `max(confirmed_at pivotu, zamknięcie świecy przemieszczenia)`; cykl życia jak w HLZE, liczony od przemieszczenia.

## 6. Ograniczenia

* Profil ze świec to przybliżenie rozkładu; przy dużych świecach (wiadomości) rozmywa POC.
* Wolumen tickowy zależy od brokera i jego serwera kwotowań – porównania między brokerami są niewłaściwe.
* Dla BTC u brokera CFD `real_volume` zwykle też jest 0 – wtedy źródło to TICK_VOLUME z tym samym zastrzeżeniem.
