# ZONE_ENGINE_ARCHITECTURE – mapa stref PMW (HLZE + DSVIE + UZICE), wersja 1.22.0

Dokument główny modułu stref: audyt stanu wyjściowego, mapa architektury, kontrakty danych, plan i raport faz 1–9.
Szczegóły silników: [HIGH_LOW_ZONE_ENGINE.md](HIGH_LOW_ZONE_ENGINE.md), [DAILY_SESSION_VOLUME_ENGINE.md](DAILY_SESSION_VOLUME_ENGINE.md);
AI / ocena setupów: [ZONE_AI_INTEGRATION.md](ZONE_AI_INTEGRATION.md); testy: [ZONE_ENGINE_TEST_REPORT.md](ZONE_ENGINE_TEST_REPORT.md).

**Tryb: `ANALYTICAL_ONLY`.** Moduł nie ma ścieżki do zleceń (sprawdzane statycznie w testach), nie zmienia trybów wykonania,
Execution Lock ani uprawnień LIVE. Wynik strefy 0–100 nie jest prawdopodobieństwem; `confidence_status` = `UNVALIDATED`.

## 1. Audyt stanu wyjściowego (faza 1)

| Obszar | Co było w repozytorium | Decyzja |
|---|---|---|
| Pivoty / swingi | `strategies/indicators.pivots` (lewa strona ≥, prawa ściśle; `confirmed_index = p + right`) | **użyte** – HLZE dodaje tylko istotność (prominence) i kandydatów prowizorycznych |
| ATR | `strategies/indicators.atr` (Wilder 14) | **użyte** |
| Sesje | `analytics/session_engine` – profile `LAB_XAU_REFERENCE_V1`, `LAB_BTC_REFERENCE_V1`, strefy IANA (DST przez `zoneinfo`), boksy FINAL, zdarzenia sweep/wybicie krawędzi | **użyte** – jedna definicja sesji w bocie: okna profili wolumenu i poziomy PREVIOUS_SESSION |
| S/R wyższego TF | `analysis/levels.zones_for_tf` | **użyte** jako potwierdzenie H1 (składnik `mtf`) |
| Konsolidacja M5 | `analysis/range_m5.detect` (zamrożony zakres, stan BROKEN_UP/DOWN) | **użyte** – poziomy CONSOLIDATION i BREAKOUT/BREAKDOWN_LEVEL |
| FVG / order block | warstwa struktury (opcja wykresu `showZones` = „FVG/OB”) | bez zmian – inne pojęcie; nowa warstwa wykresu ma osobną opcję `showZoneMap` |
| Walls / PDH-PDL | `engine/volzones.py` – linie referencyjne dnia na wykresie | bez zmian; HLZE czyta ten sam słupek D1 z MT5 (te same ceny), dodaje cykl życia strefy |
| Profil wolumenu z ticków | `mm/tsvp.py` (master models, na żądanie; wymaga strumienia ticków na żywo) | **nie użyte** w mapie: bot nie archiwizuje ticków, więc profil tickowy nie jest odtwarzalny „as of” dla historii ani dla cech ML. DSVIE liczy profil ze świec i zawsze podaje metodę (`UNIFORM_RANGE_ALLOCATION_FROM_CANDLES`). Kandydat do połączenia, gdy powstanie archiwum ticków |
| `mm/breakout_zones.py` | reguła SHADOW z własnym filtrem zmienności | bez zmian (inna rola) |
| Źródło wolumenu | słupki MT5: `tick_volume` (liczba zmian ceny), `real_volume` = 0 na OTC XAUUSD; ticki `COPY_TICKS_INFO` = kwotowania bid/ask bez strony agresora | wolumen = **TICK_VOLUME (aktywność)**; order flow, footprint, arkusz zleceń = **UNAVAILABLE** |
| Głębokość danych | bufor mostu 500 świec na TF (≈ 41 h M5) – za mało na bazę 5 sesji | `ZoneService` czyta do 2016 M5 (7 dni) przez `bridge.symbol_bars` (niski priorytet), H1/D1 z buforów |
| Cechy ML | `ml/features.py` (MQ-FEAT-1.0.0), cechy ledgera ocen | nowa wersja MQ-FEAT-1.1.0 = nadzbiór 1.0.0 |
| Wykres | lightweight-charts 5, prymitywy `ZonesPrimitive` / `BoundedBoxesPrimitive` | **użyte** – nowa warstwa to kolejna instancja `BoundedBoxesPrimitive` |

Ustalenia audytu, które wpłynęły na projekt: brak prawdziwego wolumenu transakcyjnego dla XAUUSD (każda informacja wolumenowa jest
oznaczona jako obserwacja aktywności tickowej), brak archiwum ticków (profile ze świec), krótki bufor mostu (osobny odczyt historii).

## 2. Mapa architektury

```
MT5 (zamknięte świece M5/M15 z symbol_bars, H1/D1 z buforów mostu)
   │  Series.from_bars(as_of): tylko świece zamknięte, open + TF <= as_of; duplikat slotu -> ostatnia rewizja
   ▼
HLZE  zones/hlze.py   swingi M5/M15 (prowizoryczne/potwierdzone) -> strefy + cykl życia; równe szczyty/dołki; poprzedni dzień,
   │                  poprzednia sesja (session_engine), dzień bieżący (prowizorycznie), konsolidacja (range_m5)
   ▼
DSVIE zones/dsvie.py  źródło wolumenu -> profile sesji (POC/VAH/VAL/HVN/LVN, stany) -> kontekst sesji -> strefy popytu/podaży z dowodami
   ▼
UZICE zones/uzice.py  normalizacja, łączenie tej samej polaryzacji, konflikty, punktacja z karami -> jedna mapa stref
   ▼
ZE.compute_map  zones/engine.py   mapa PMW-ZONE-1.0 (map_id, wersje, stan danych, strefy, profile, kontekst, podsumowanie)
   │
   ├── ZoneService (zones/service.py): przeliczenie raz na nową zamkniętą M5 (wątek, poll 5 s), SQLite data/zones/zones.sqlite
   │      (ostatnie 300 map, dziennik zdarzeń stref UNIQUE(instrument, zone_id, status)), widok historyczny at(as_of)
   ├── API /api/v1/zones/{map,status,events,profiles,context}  ->  wykres (warstwa „Strefy H/L + profil sesji”)
   ├── EvaluationService (SHADOW): zone_context każdego setupu, flaga ZONE_ROOM_INSUFFICIENT -> REDUCE w ocenie SHADOW
   └── ml/features.py MQ-FEAT-1.1.0: zone_block() woła TEN SAM compute_map na cięciu as-of widoku (26 cech)
```

Jedna funkcja `compute_map` obsługuje mapę na żywo, widok historyczny wykresu i cechy ML – żaden konsument nie odtwarza stref
własnymi regułami (wymóg „downstream modules must not recalculate”).

## 3. Kontrakty danych

### 3.1 Strefa zunifikowana (`schema_version` = `PMW-ZONE-1.0`)

| Pole | Znaczenie |
|---|---|
| `zone_id` | `UZ-` + sha256(id członka-kotwicy) – kotwica = najwcześniej potwierdzony członek; dołączenie nowego członka nie zmienia id |
| `zone_type` | DEMAND, SUPPLY, LIQUIDITY_CLUSTER, EQUAL_HIGHS/LOWS, PREVIOUS_DAY_HIGH/LOW, PREVIOUS_SESSION_HIGH/LOW, SWING_HIGH/LOW, CONSOLIDATION_HIGH/LOW, BREAKOUT_LEVEL, BREAKDOWN_LEVEL, INTRADAY_HIGH/LOW (priorytet w tej kolejności) |
| `polarity` / `role` | HIGH (opór) / LOW (wsparcie); rola względem bieżącej ceny: RESISTANCE / SUPPORT / AT_PRICE |
| `timeframes` | TF członków (M5, M15, D1) |
| `lower_price`, `upper_price`, `mid_price`, `width_atr` | granice i szerokość w ATR M5 |
| `created_at`, `confirmed_at`, `last_updated_at` | utworzenie (zamknięcie świecy pivotu), potwierdzenie (najwcześniejsze potwierdzenie członka), czas mapy |
| `status`, `provisional` | PROVISIONAL / ACTIVE / TESTED / WEAKENED / SWEPT (strefy BROKEN/EXPIRED trafiają do `expired`) |
| `structure_evidence`, `volume_evidence` | dowody z `group`, `kind`, `root`, `detail`, `evidence_type` (PRICE_ACTION_INFERENCE / VOLUME_OBSERVATION) |
| `reaction_metrics` | retests, rejection_max_atr, penetration_max, swept, age_bars |
| `score_components`, `penalty`, `confluence_score` | składniki (structure/volume/reaction/mtf/freshness/data_quality), kary, wynik 0–100 |
| `flags`, `conflicting_zone_ids` | WIDE, PROVISIONAL, CONFLICT (+ id stref przeciwnych) |
| `confidence_status` | zawsze `UNVALIDATED` (brak skalibrowanego modelu wyników stref) |
| `invalidation_rules` | przełamanie wyłącznie zamknięciem o ≥ `break_close_atr` ATR; knot = test/sweep |
| `source_zone_ids`, `member_types`, `liquidity` | pochodzenie (id stref HLZE/DSVIE), typy członków, płynność **wnioskowana** |
| `distance_atr` | odległość od ceny w ATR M5 |

### 3.2 Mapa (`ZE.compute_map`, wersja `PMW-ZONES-MAP-1`)

`map_id` (`ZM-` + hash instrumentu, as_of, wersji silników i stanu stref), `schema_version`, `instrument`, `symbol`, `as_of`,
`versions` {map, hlze, dsvie, uzice, schema}, `data` {state OK / DEGRADED / STALE / INSUFFICIENT_HISTORY, reasons, bars},
`zones`, `m5`, `m15`, `levels`, `demand_supply`, `profiles` {developing, completed (12 ostatnich), profile_set}, `context`,
`volume_source`, `expired` (30 ostatnich), `htf_sr`, `price`, `atr_m5`, `session_boxes`, `summary` {nearest_support,
nearest_resistance, zones, provisional}, `mode` = `ANALYTICAL_ONLY`.

Stan danych: `INSUFFICIENT_HISTORY` (< 60 zamkniętych M5) → brak stref; `STALE` (ostatnia zamknięta M5 starsza niż 3 świece);
`DEGRADED` (rozwijający się profil sesji jest STALE). Konsumenci nie traktują mapy innej niż OK jako potwierdzonej.

### 3.3 API (tylko odczyt)

| Endpoint | Zwraca |
|---|---|
| `GET /api/v1/zones/map?tf=ALL|M5|M15&as_of=&full=` | widok dla wykresu (strefy z polami rysowanymi na wykresie, profil rozwijający się i ostatni zakończony; ≈ 13 KB zamiast ≈ 60 KB pełnych stref) albo pełna mapa (`full=true`, z dowodami i punktacją); `as_of` = widok historyczny (świece ucięte na as_of); brak danych → `{"status": "NO_MAP", "reason"}` |
| `GET /api/v1/zones/status` | stan serwisu (przebiegi, czas obliczeń, ostatni błąd, stan danych, źródło wolumenu, wersje) |
| `GET /api/v1/zones/events?limit=` | dziennik zmian statusu stref (bez duplikatów) |
| `GET /api/v1/zones/profiles` | profile sesji + kontekst sesji + źródło wolumenu |
| `GET /api/v1/zones/context?direction=&entry=&stop=&cost=` | kontekst stref dla planu setupu (najbliższe wsparcie/opór, miejsce do strefy przeciwnej po kosztach w R, flagi, 26 cech) |

## 4. Wydajność i odporność

* Przeliczenie raz na nową zamkniętą M5, nigdy na tick. Pomiar: 2016 M5 + M15/H1/D1 (dane syntetyczne) ≈ 0,2–0,3 s na mapę;
  ścieżka POC rozwijającego się profilu liczona przyrostowo.
* Stabilne id: strefy HLZE z hash(TF, typ, czas pivotu), strefy zunifikowane z id kotwicy, profile z hash(instrument, profil sesji,
  sesja, data lokalna, bin, TF). Restart/reconnect na tych samych świecach daje tę samą mapę (`map_id`) – test.
* Dziennik zdarzeń: `INSERT OR IGNORE` na (instrument, zone_id, status) – powtórzone obliczenie lub restart nie dubluje zdarzeń.
* Błąd odczytu (np. terminal niepołączony) nie zatrzymuje bota: pętla zapisuje `last_error`, API odpowiada `NO_MAP`.
* `zones.enabled = false` wyłącza pętlę (mapa nie jest liczona automatycznie).

## 5. Bezpieczeństwo i granice

* Pakiet `zones/` nie importuje modułów wykonania (test statyczny `Isolation` – te same zakazy co warstwa oceny).
* Jedyny wpływ na decyzje: w **ocenie SHADOW** setupu (`evaluation/engine.py`) silna strefa przeciwna bliżej niż `min_room_r` po
  kosztach zmienia decyzję oceny na REDUCE – tylko przy mapie w stanie OK. Ocena SHADOW nie steruje zleceniami (decyzja O2:
  SHADOW do 200 ocen). Ścieżki wykonania S01–S12 i SCALPING/HEDGING są bez zmian.
* Modele produkcyjne: brak automatycznego retreningu i podmiany czempiona; czempion 1.0.0 ładuje się dalej (sprawdzone testem).
* Żadnych danych fikcyjnych w bocie: brak wolumenu = `NONE` i profile INVALID; brak sesji = brak poziomów sesji.

## 6. Plan i raport faz

| Faza | Zakres | Pliki | Testy | Wynik |
|---|---|---|---|---|
| 1 Audyt | inwentarz stref, swingów, sesji, źródeł wolumenu, wykresu, cech | – | – | §1 |
| 2 HLZE | swingi, strefy, cykl życia, równe szczyty/dołki, poziomy dnia/sesji/konsolidacji | `zones/series.py`, `zones/hlze.py`, `config.py` (`ZonesConfig`) | `test_zones`: Pivots, Lifecycle | zaliczone |
| 3 DSVIE | źródło wolumenu, profile sesji (DST), stany, wolumen względny, kontekst, popyt/podaż z dowodami | `zones/dsvie.py`, `mt5/bridge.py` (`rv` w symbol_bars) | Profiles, DemandSupply | zaliczone |
| 4 UZICE | łączenie, konflikty, punktacja bez podwójnego liczenia, kary | `zones/uzice.py`, `zones/engine.py` | Unify, NoLookAhead, MapAndFeatures | zaliczone |
| 5 Serwis + API | pętla M5, SQLite, zdarzenia, widok historyczny, 5 endpointów | `zones/service.py`, `runtime.py`, `api/app.py` | ServiceRestart | zaliczone |
| 6 Ocena setupów | zone_context, REDUCE przy braku miejsca (SHADOW), strażnik look-ahead | `zones/features.py`, `evaluation/{contract,engine,service}.py` | EvaluationIntegration, EvaluationLookAhead | zaliczone |
| 7 ML | MQ-FEAT-1.1.0 (26 cech stref), zgodność 1.0.0 w trenerze i przy ładowaniu modelu | `ml/features.py`, `ml/trainer.py`, `ml/models.py` | MLSchema + `test_ml` | zaliczone |
| 8 Wykres | warstwa „Strefy H/L + profil sesji”, etykiety, podpowiedź pod kursorem | `ChartPanel.tsx`, `ChartToolbar.tsx`, `BotChartsPage.tsx`, `AiAnalysisPage.tsx`, `styles.css` | build + kontrola w przeglądarce | [raport testów](ZONE_ENGINE_TEST_REPORT.md) |
| 9 Walidacja | testy pełne, demo, raport; walidacja predykcyjna na danych klienta – **do wykonania** | `tests/test_zones.py`, dokumenty | pełny zestaw | [raport testów](ZONE_ENGINE_TEST_REPORT.md) |

### Problemy znalezione i naprawione w trakcie

* `ml/models.py` odrzucał model o innej wersji schematu cech – po podbiciu do 1.1.0 czempion 1.0.0 przestałby się ładować.
  Teraz akceptowane są wersje z `COMPATIBLE_SCHEMAS` (model czyta własną zapisaną listę kolumn).
* Bramka „≥ 40 świec H1” była liczona przed cięciem as-of (możliwy wpływ przyszłych świec na to, czy liczono S/R H1) – cięcie przeniesione przed bramkę.
* Poziomy poprzedniej sesji czytały złe klucze krawędzi boksu (`high`/`low` zamiast `HIGH`/`LOW`) – stan krawędzi był gubiony.
* Pierwsza wersja punktacji nasycała się (≈ 95/100 dla większości stref, bo każda etykieta jednego pivotu i każdy profil liczyły się
  osobno) – teraz struktura liczy się raz na kategorię, reakcja = najsilniejszy członek, wolumen tylko z 4 najnowszych profili;
  na danych syntetycznych rozkład wyników 13–88.
* `nearest` traktował strefę popytu „przy cenie” jako opór – wybór jest teraz kierunkowy według polaryzacji.
* API przy niepołączonym terminalu zwracało błąd 500 przy pierwszym obliczeniu na żądanie – teraz `NO_MAP` z przyczyną.

### Otwarte kwestie / następne kroki

1. **Walidacja predykcyjna** (warunek jakiegokolwiek wpływu poza SHADOW): walk-forward na historii klienta z kosztami – porównanie
   ocen/modeli z cechami stref i bez nich (Brier, log loss, wynik netto w R). Do tego czasu wynik strefy jest wyłącznie opisowy.
2. Wagi punktacji (25/25/20/15/10/5) i progi (`strong_zone_score` 60, `min_room_r` 1,0) to wartości projektowe, nie dopasowane do danych.
3. Archiwum ticków → profil tickowy (`mm/tsvp`) jako alternatywna metoda alokacji w DSVIE.
4. Monitorowanie w trybie Paper: dziennik zdarzeń stref + `zone_context` w ledgerze ocen; LIVE wymaga osobnej, jawnej zgody.
