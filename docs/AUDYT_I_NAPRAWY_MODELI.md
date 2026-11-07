# Audyt i naprawy modeli – 1.33.0 (specyfikacja AUD)

Zakres: wszystkie miejsca, w których bot tworzy, przenosi lub używa prognoz modeli. Każde znalezisko zostało **odtworzone testem
przed poprawką**, następnie naprawione i zabezpieczone testem regresji. Pozycje bez odtworzenia są opisane jako nieodtworzone.

| # | Znalezisko | Odtworzenie | Naprawa | Test |
|---|---|---|---|---|
| A1 | Kontrakt PMW-PRED-1 przepuszczał `True` jako prawdopodobieństwo, NaN/±Inf i wynik bez schematu dla zadania | 4/4 przypadki przechodziły walidację | PMW-PRED-2: liczby skończone (nigdy bool), schematy wyników per typ zadania (rozkład, zdarzenie, regresja z przedziałem, zmienność ze skalą, para, mikrostruktura, filtr, akcja RL, sentyment), JSON bez NaN; model nie-READY nie ma wyniku | `test_integration_u1` |
| A2 | Wymyślony horyzont `horizon_bars=1` dla pomiarów stanu | odtworzone | horyzont: dodatnia liczba świec **albo** sekund dla prognoz; pomiar stanu może mieć `null` | `test_integration_u1` |
| A3 | Brak interwału M3 w łańcuchu (rejestr TF, most, eksport, TrainHub, Kronos) – modele M3 nie mogły dostać danych | odtworzone | M3 w rejestrze TF, FakeMT5, fallback M1→M3 z flagą `complete`, eksport, TrainHub (`TF_S`, `HTF_OF`), Kronos (TF + horyzont) | `test_integration_u1`, `test_bridge_engine` |
| A4 | `dxy_missing` ustawiane na sztywno, niezależnie od rzeczywistej dostępności DXY | odtworzone | cecha = rzeczywista dostępność (MQ-FEAT-1.2.0) + adapter starszych modeli trenowanych na starej definicji | `test_integration_u1` |
| A5 | Kronos REQUIRED dopuszczony raz, ważny także po zmianie symbolu / horyzontu / ustawień / wag | odtworzone | dopuszczenie związane z odciskiem (symbol, horyzont, ustawienia, pasmo neutralne, rewizje wag); nieaktualne → setup wstrzymany (WAIT) z powodem | `test_kronos_bot`, `test_integration_u1` |
| A6 | Pamięć podręczna predykcji po aktywacji nowej wersji (AUD 3.2) | **nie odtworzono** (klucz zawierał już wersję) | dodatkowo `invalidate()` po aktywacji / rollbacku / zmianie roli | `test_families_u4` |
| A7 | Regresja po A3: pętla mostu MT5 z `KeyError: 'M3'` (brak M3 w `TF_POLL`) | odtworzone w regresji U2 | `TF_POLL["M3"] = 1.5 s` | `test_bridge_engine` |
| A8 | ARIMA / SARIMAX na surowych log-zwrotach (~1e-3): optymalizator MLE nie zbiegał; SARIMAX na H1 z grupowaniem zmienności → BLOCKED we wszystkich dopasowaniach | odtworzone (`tools/validate_families_synthetic.py`: SARIMAX BLOCKED; dopasowania niezbieżne w 3/4 przypadków) | dopasowanie na zwrotach skalowanych do wariancji 1 (skala w artefakcie, prognozy i metryki z powrotem w jednostkach log-zwrotu; stare artefakty = skala 1) | `test_families_u4.test_sarimax_converges_on_h1_with_volatility_clustering` |
| A9 | Studio szukało danych bota w `<katalog>/data`, a bot w Windows używa katalogu z reguły `default_data_dir` | odczyt kodu (rozjazd reguł) | Studio używa tej samej reguły co bot (`MQ_BOT_DATA_DIR`, inaczej `default_data_dir`); launcher Go ustawia zmienne jawnie | `test_ui_pmw133` (uruchomienie Studio z bota), Go `desktop_test` |
| A10 | Wspólny limit portfela sprawdzany osobno przez obie ścieżki (check-then-act) – dwie ścieżki naraz mogły przekroczyć `max_open_positions` | odtworzone (replay: limit 2, 6 żądań → 6 przechodzi) | atomowa rezerwacja PMW-ARC-1 (`decision/ledger.py`) | `test_decision_arc_u6` (8 wątków, limit 1 → 1) |

## Nowe rodziny (PMW-FAM-1)
15 rodzin dostało wspólny adapter. Szczegóły są w `docs/MAPA_INTEGRACJI_MODELI.md`, karty w `MODEL_CARDS/families/`.
* **Trzy osie stanu:** implementacja, artefakt, użycie.
* **Magazyn artefaktów:** manifest, sumy SHA-256, próbka inferencji sprawdzana przy aktywacji, rollback.
* **Role:** OFF / SHADOW / ASSIST. ASSIST wymaga walidacji APPROVED na danych REAL.

Zasady trenowania i oceny:
* Chronologiczny podział z holdoutem. Bramka liczona tylko na części rozwojowej.
* Odniesienia: random walk, EWMA, płaska pozycja, momentum.
* Koszty liczone raz.
* Wykonanie RL na następnym open.
* Kanał breakout bez bieżącej świecy (brak wiedzy wstecznej).

## Zachowane bez zmian
Execution Lock pozostaje wycofany i nie wrócił. Zachowane są tryby SIGNALS/PAPER/AUTO DEMO/AUTO LIVE, STOP nowych wejść i limity
użytkownika. Żaden model nie składa zleceń.
