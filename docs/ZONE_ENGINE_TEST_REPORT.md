# ZONE_ENGINE_TEST_REPORT – mapa stref PMW 1.22.0 (26.10.2026)

Zakres: [ZONE_ENGINE_ARCHITECTURE.md](ZONE_ENGINE_ARCHITECTURE.md). Wszystkie dane w testach i w demo są **syntetyczne**
(symulator terminala) – sprawdzają reguły, kontrakty i integrację, **nie** wartość predykcyjną stref.

## 1. Testy jednostkowe i integracyjne – `tests/test_zones.py` (41 testów)

| Klasa | Co sprawdza | Wynik |
|---|---|---|
| `Pivots` (4) | pivot prowizoryczny do domknięcia prawej strony; `created_at` = zamknięcie świecy pivotu, `confirmed_at` = zamknięcie p+right (bez datowania wstecz); swing o wychyleniu < 0,6 ATR pomijany; strefa za szeroka odrzucona, szeroka oznaczona WIDE | OK |
| `Lifecycle` (7) | ACTIVE → TESTED → WEAKENED (więcej testów = słabsza); kilka świec w strefie = jeden test; sweep wymaga zamknięcia z powrotem; knot + zamknięcie tuż za granicą (< 0,1 ATR) + powrót = SWEPT, nie BROKEN; przełamanie tylko zamknięciem i zmiana roli w BREAKOUT_LEVEL od świecy przełamania; EXPIRED; równe szczyty znane od potwierdzenia drugiego pivotu, płynność INFERRED, min. szerokość | OK |
| `NoLookAhead` (3) | mapa liczona przy `as_of` z pełną historią = mapa z danych uciętych na `as_of` (identyczny `map_id`, strefy i profile; żadna data potwierdzenia/utworzenia > as_of); świeca formująca się i `closed=false` pomijane; < 60 M5 → INSUFFICIENT_HISTORY bez stref, stare dane → STALE i 0 pkt jakości danych | OK |
| `Profiles` (6) | histogram (podział świecy wg pokrycia), POC (remis → niższa cena), value area 70%, HVN/LVN na znanym przykładzie; klasyfikacja źródła wolumenu (TICK / EXCHANGE / NONE, order flow UNAVAILABLE); **DST**: LONDON 23.10 = 07:00 UTC, 26.10 = 08:00 UTC, NEW_YORK 26.10 = 12:20 UTC; profil zakończony identyczny po dobie dodatkowych danych, rozwijający się używa tylko zamkniętych świec (36 świec o 10:00); dziura w danych → INVALID z przyczyną, stary rozwijający się → STALE; wolumen względny tej samej sesji w tym samym czasie | OK |
| `DemandSupply` (2) | sama akcja ceny (odrzucenie + przemieszczenie) nie tworzy popytu; ze skokiem aktywności tickowej – DEMAND z dowodami PRICE_ACTION_INFERENCE / VOLUME_OBSERVATION, `order_flow_verified = false` | OK |
| `Unify` (7) | łączenie zachowuje pochodzenie i id kotwicy (nowy członek nie zmienia id); za szeroki klaster nie jest łączony; przeciwne polaryzacje nie są łączone i dostają CONFLICT + karę; skorelowane dowody liczone raz (8 swingów M5 w jednym miejscu = 6 pkt struktury); determinizm przy odwróconej kolejności wejścia; wynik w 0–100; wolumen = 0 bez źródła, jakość danych = 0 przy STALE; `nearest` kierunkowy | OK |
| `MapAndFeatures` (3) | kontrakt mapy (pola schematu, brak duplikatów id, tryb ANALYTICAL_ONLY), czas < 10 s; 26 cech, NaN bez mapy; flaga braku miejsca tylko dla silnej i bliskiej strefy przeciwnej | OK |
| `EvaluationIntegration` (1) | ZONE_ROOM_INSUFFICIENT przy danych OK → REDUCE; przy STALE → bez wpływu (notatka); bez skalibrowanego P → DEFER (strefy nie tworzą prawdopodobieństwa) | OK |
| `EvaluationLookAhead` (2) | ledger: mapa późniejsza niż decyzja odrzucona, mapa znana w chwili decyzji zapisana w `zone_context` | OK |
| `ServiceRestart` (2) | dwa przeliczenia i restart serwisu: ten sam `map_id` i id stref, liczba zdarzeń bez zmian, jedna mapa w bazie; widok historyczny bez stref potwierdzonych po `as_of`; widok wykresu filtruje TF; brak terminala → brak mapy, bez wyjątku, przyczyna w statusie | OK |
| `MLSchema` (3) | 1.1.0 jest nadzbiorem 1.0.0; FeatureEngine faktycznie wypełnia blok stref (≥ 20 z 26 cech, a nie ciche NaN z obsługi błędu; koszt = kwotowany spread); model zapisany jako MQ-FEAT-1.0.0 (i 1.1.0) ładuje się i daje ten sam wynik dla wiersza z dodatkowymi kolumnami stref; nieznana wersja schematu odrzucona | OK |
| `Isolation` (1) | pakiet `zones/` nie importuje modułów wykonania i nie odwołuje się do `order_send`, gateway, PaperBroker, PositionManager, SHExecutor | OK |

Wynik: `python -m unittest test_zones` – **Ran 41 tests, OK**. Testy powiązane: `test_evaluation` (zone_context w ocenie) – OK;
`test_ml` (trening, rejestr i predykcja przy schemacie 1.1.0; `TestNoLookAhead` – wszystkie cechy, w tym 26 cech stref,
identyczne po dodaniu do widoku 10 h przyszłych świec) – wynik w pełnym przebiegu (§2).

## 2. Pełny zestaw testów offline

`tools/run_tests.py` (wszystkie `tests/test_*.py`): przebieg w toku – wynik uzupełniany po jego zakończeniu.

## 3. Sprawdzenie w działającym bocie (demo, symulator terminala, 26.10.2026)

| Sprawdzenie | Wynik |
|---|---|
| ZoneService w pętli bota | 2 przeliczenia w pierwszych minutach (raz na zamkniętą M5), `data_state` OK, 2015 M5 / 671 M15 / 306 D1 z odczytu historii, 33 strefy (1 prowizoryczna) |
| Czas | 2,8 s na przebieg w bocie (odczyt historii przez kolejkę MT5 + CPU dzielony z równolegle działającym pełnym zestawem testów); samo `compute_map` offline 0,24–0,27 s na tej samej ilości danych. Status pokazuje teraz osobno `last_read_ms` i `last_compute_ms` |
| Źródło wolumenu | `TICK_VOLUME`, 2015/2015 świec z tick volume, 0 z real volume; order flow / footprint / arkusz UNAVAILABLE |
| Dziennik zdarzeń | 65 zdarzeń, 65 różnych par (strefa, status) – bez duplikatów |
| Widok historyczny `as_of=10:00` | 28 stref, najpóźniejsze potwierdzenie 09:55 – nic z przyszłości |
| Profile | 12 zakończonych, rozwijający się NEW_YORK (DEVELOPING), wolumen względny 0,988, cena poniżej VA poprzedniego profilu |
| `/api/v1/zones/context` (LONG) | strefa przeciwna SWING_HIGH 0,127 R po kosztach; brak flagi, bo jej wynik < 60 (strefa prowizoryczna) |
| Ocena setupów | w oknie demo żaden setup nie doszedł do oceny – `zone_context` w ledgerze sprawdzony tylko testami (§1) |

## 4. Wykres (Chromium, 1600×1000, strona „Wykresy bota”)

* Przełącznik „Strefy H/L + profil sesji” obecny; po włączeniu panel woła `/api/v1/zones/map?tf=…` (HTTP 200), bez błędów konsoli.
* Strefy rysowane od chwili potwierdzenia z etykietą `typ TF status wynik`; prowizoryczne – przerywana ramka i dopisek „PROW.”
  (rozróżnienie nie tylko kolorem); POC/VAH/VAL ostatniej zakończonej sesji ciągłe, rozwijającej się – przerywane z dopiskiem „rozw.”.
* Podpowiedź pod kursorem na strefie: `SWING_LOW M15/M5 ACTIVE 65 | 3456,63–3457,16 | testy 0 | potw. 14:25 | wolumen: TICK_VOLUME
  (wynik nie jest prawdopodobieństwem)`; po wyłączeniu warstwy podpowiedź i strefy znikają.
* Na D1/H8 strefy M5 są cienkimi liniami (skala) – warstwa jest przeznaczona głównie dla M5/M15.

## 5. Czego NIE sprawdzono

* **Wartość predykcyjna** stref, wag punktacji i progu `min_room_r` – brak danych klienta w środowisku; plan w
  [ZONE_AI_INTEGRATION.md](ZONE_AI_INTEGRATION.md) §6. Nie twierdzimy, że strefy poprawiają ROI ani skuteczność.
* Zachowanie na prawdziwym terminalu MT5 (tick volume prawdziwego brokera, przerwy w notowaniach, święta) – tylko symulator.
* Wydajność na słabszym komputerze klienta – zmierzona tylko w kontenerze.
