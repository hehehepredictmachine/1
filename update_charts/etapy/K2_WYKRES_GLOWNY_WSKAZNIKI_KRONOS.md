# K2 – Wykres główny, wskaźniki, RSI / MACD, Kronos

**Wzorzec (`charts.js`):** `computeAll` (tylko część wskaźników), `ema`, `rsiF`, `atrF`, `sarF`, AVWAP ±σ, `heikin`, `niceStep`, `drawMain`, `drawKronos`, `drawChart`, obsługa myszy (przeciąganie, kółko = zoom, 2× klik = teraz, hover, `khover`), `renderOpts` (zakładki WSKAŹNIKI i WYKRES), stopka Kronos (`#kr-dir`, `#kr-delta`, `#kr-read`, `#kr-meta`).

## Zakres

1. **Rysowanie 1:1.** `drawMain` i `drawKronos` przenosisz bez zmian: siatka, osie, formaty czasu (`fmtT`) i ceny (`fmtP`), świece / Heikin-Ashi / linia, wolumen, EMA 20/50, AVWAP ±1σ/±2σ, SAR, okna RSI 14 i MACD 12·26·9, znacznik ostatniej ceny z błyskiem, linia „TERAZ”, odczyt OHLC + wskaźników w `#mc-read`, odczyt pod kursorem.

2. **Dane świec:** `GET /api/v1/candles?tf=` (+ `store.barTick[tf]` na żywo, `bar_closed`). Instrument inny niż symbol silnika: zgodnie z rozstrzygnięciem K0. Pole `closed` = świeca zamknięta.

3. **Wskaźniki – jedna prawda.**
   - Jeśli odpowiedź `candles` zawiera wartości wskaźników albo projekt ma ich obliczenia (WtcTower / chartlab), użyj ich.
   - Wzory z wzorca (`ema`, `rsiF`, `atrF`, `sarF`, AVWAP) zostają **tylko jako kontrola zgodności**: test jednostkowy porównuje je z projektem na tych samych świecach. Różnica > 1e-6 → zgłoś (nie wybieraj po cichu).
   - W trybie testowym wskaźniki liczone są z `fx.candles` tą samą ścieżką co w produkcji.

4. **Okno ceny:** `CH.view` (domyślnie 120 świec), `CH.offset`, `yMin/yMax` z widocznych świec – jak w `loadSeries` wzorca (bez generatora).

5. **Kronos:**
   - status `GET /api/v1/kronos` (SHADOW / niezainstalowany → stan pusty z nazwą `33_KRONOS_INSTALUJ.bat`);
   - prognoza `GET /api/v1/kronos/forecast?instrument=&tf=` tylko M1/M5/M15/M30/H1, inny TF → `TIMEFRAME_NOT_ALLOWED`;
   - mapowanie na `CH.kr.fc` (D1 §3.6): `pred`, `paths` (ścieżki niepewności), `direction`, `neutral_band`, `horizon`, `created_at`, `is_current`; seria Kronos przesunięta do ostatniego zamknięcia (jak `sh` we wzorcu – przesunięcie, nie generacja);
   - **brak pola `paths` w API → nie rysujesz wachlarza** i pokazujesz w stopce „brak ścieżek niepewności”; nie symulujesz ich;
   - przycisk „PRZELICZ” = ponowny GET, bez zapisu.

6. **Odświeżanie:** świece na żywo ze store; reszta po `bar_closed` wybranego TF; polling ≥ 5 s.

## Kryteria K2
- [ ] Scenariusz testu 1:1 `K1_xau_m5_wskazniki`: obszary `wykres_glowny`, `odczyt`, `kronos`, `kronos_stopka`, `naglowek` w progu (karta planu może jeszcze nie przechodzić – K3).
- [ ] Test zgodności wskaźników przechodzi.
- [ ] Kronos niezainstalowany → stan pusty jak w D1, zrzut w raporcie.
